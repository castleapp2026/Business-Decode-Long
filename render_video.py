import os, sys, requests, json, subprocess, socket, gc, random, re, time
import urllib.parse
from PIL import Image
import io
import urllib3.util.connection as urllib3_cn
import moviepy.editor as mpe
from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip, CompositeVideoClip, ImageClip
import moviepy.video.fx.all as vfx

# Force IPv4 to bypass strict server blocks for API requests
def allowed_gai_family(): return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

# --- Configuration for Business Case Studies ---
chat_id = os.environ.get('CHAT_ID')
pexels_key = os.environ.get('PEXELS_API_KEY')
scenes_data = json.loads(os.environ.get('SCENES_DATA', '[]'))
bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '8798779179:AAH53t28qW6g7QTsB8nGCEswNJz2DXR9ssU')
video_title = os.environ.get('TITLE', 'Business Case Study')
thumbnail_prompt = os.environ.get('THUMBNAIL_PROMPT', 'Cinematic business thumbnail')
video_desc = os.environ.get('DESCRIPTION', 'Business case study video.')

TARGET_W, TARGET_H = 1920, 1080
used_videos = set()
video_files, audio_files = [], []
last_successful_media = None  

print(f"Total Scenes to render: {len(scenes_data)}")

def get_pexels_video(query):
    try:
        res = requests.get(f"https://api.pexels.com/videos/search?query={query}&per_page=15&orientation=landscape", headers={"Authorization": pexels_key}, timeout=15).json()
        if res.get('videos'):
            for v in res['videos']:
                url = v['video_files'][0]['link']
                if url not in used_videos:
                    used_videos.add(url)
                    return url
            return res['videos'][0]['video_files'][0]['link']
    except: return None

# ==========================================
# Process Each Scene (Business Case Study Engine)
# ==========================================
for i, scene in enumerate(scenes_data):
    keyword = scene.get('keyword', 'business').strip()
    image_prompt = scene.get('image_prompt', keyword).strip()
    text_line = scene.get('text', ' ').strip() or " "

    # --- 1. Audio Pipeline (MadhurNeural + Deep Audio Filter) ---
    raw_audio_path = f"raw_audio_{i}.mp3"
    norm_audio_path = f"audio_{i}.wav"
    subprocess.run(['edge-tts', '--voice', 'hi-IN-MadhurNeural', '--text', text_line, '--write-media', raw_audio_path])

    if os.path.exists(raw_audio_path):
        audio_filter = "silenceremove=stop_periods=-1:stop_duration=0.3:stop_threshold=-35dB,bass=g=5:f=110,treble=g=3:f=8000"
        subprocess.run(['ffmpeg', '-y', '-i', raw_audio_path, '-af', audio_filter, '-ar', '44100', '-ac', '2', norm_audio_path], check=True)
        out = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', norm_audio_path])
        # FIXED: Removed the '+ 0.2' desync issue so video perfectly matches audio length
        scene_duration = float(out.decode('utf-8').strip()) 
    else:
        scene_duration = 3.0
        subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=stereo', '-t', str(scene_duration), norm_audio_path], check=True)

    final_audio_path = norm_audio_path
    if os.path.exists("whoosh.mp3") and i > 0:
        mixed_audio = f"mixed_audio_{i}.wav"
        subprocess.run(['ffmpeg', '-y', '-i', norm_audio_path, '-i', 'whoosh.mp3', '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=0[aout]', '-map', '[aout]', '-ar', '44100', '-ac', '2', mixed_audio], check=True)
        final_audio_path = mixed_audio

    audio_files.append(os.path.abspath(final_audio_path))

    # --- 2. Smart Visual Fetching (Pexels + AI Image Fallback) ---
    video_url = get_pexels_video(keyword)
    norm_video_path = f"video_{i}.mp4"
    raw_media_path = f"raw_media_{i}.mp4"
    
    try:
        if video_url:
            req = requests.get(video_url, timeout=45)
            with open(raw_media_path, "wb") as f: f.write(req.content)
            vclip = VideoFileClip(raw_media_path).fx(vfx.speedx, 1.2)
            vclip = vclip.fx(vfx.loop, duration=scene_duration) if vclip.duration < scene_duration else vclip.subclip(0, scene_duration)
            last_successful_media = {"type": "video", "path": raw_media_path}
        else:
            print(f"⚠️ Generating AI Image for '{image_prompt}'")
            raw_media_path = f"raw_media_{i}.jpg"
            ai_prompt_encoded = urllib.parse.quote(f"Epic cinematic concept art, {image_prompt}, highly detailed, 8k resolution, Unreal Engine 5 render, dramatic contrast, pure textless photograph, no typography")
            req = requests.get(f"https://image.pollinations.ai/prompt/{ai_prompt_encoded}?width=1920&height=1080&nologo=true", timeout=45)
            img = Image.open(io.BytesIO(req.content)).convert("RGB")
            img.save(raw_media_path, "JPEG")
            vclip = ImageClip(raw_media_path).set_duration(scene_duration)
            last_successful_media = {"type": "image", "path": raw_media_path}

        vclip = vclip.resize(height=TARGET_H) if (vclip.w / vclip.h) > (TARGET_W / TARGET_H) else vclip.resize(width=TARGET_W)
        vclip = vclip.crop(x_center=vclip.w/2, y_center=vclip.h/2, width=TARGET_W, height=TARGET_H)
        
        motion_type = random.choice(['zoom_in', 'zoom_out'])
        zoom_factor = 1.05 
        z_clip = vclip.resize(lambda t: 1.0 + (zoom_factor - 1.0) * (t / scene_duration)).set_position(('center', 'center')) if motion_type == 'zoom_in' else vclip.resize(lambda t: zoom_factor - (zoom_factor - 1.0) * (t / scene_duration)).set_position(('center', 'center'))

        final_scene = CompositeVideoClip([z_clip], size=(TARGET_W, TARGET_H)).set_duration(scene_duration)
        final_scene.write_videofile(norm_video_path, fps=24, codec="libx264", audio=False, preset="ultrafast", ffmpeg_params=['-pix_fmt', 'yuv420p', '-vf', 'setsar=1'], logger=None)

    except Exception as e:
        print(f"Visual Error at scene {i}: {e}")
        if last_successful_media and os.path.exists(last_successful_media["path"]):
            fallback_clip = VideoFileClip(last_successful_media["path"]).fx(vfx.loop, duration=scene_duration) if last_successful_media["type"] == "video" else ImageClip(last_successful_media["path"]).set_duration(scene_duration)
            fallback_clip = fallback_clip.resize(height=TARGET_H).crop(x_center=fallback_clip.w/2, y_center=fallback_clip.h/2, width=TARGET_W, height=TARGET_H)
            z_clip = fallback_clip.resize(lambda t: 1.05 - (0.05) * (t / scene_duration)).set_position(('center', 'center'))
            final_scene = CompositeVideoClip([z_clip], size=(TARGET_W, TARGET_H)).set_duration(scene_duration)
            final_scene.write_videofile(norm_video_path, fps=24, codec="libx264", audio=False, preset="ultrafast", ffmpeg_params=['-pix_fmt', 'yuv420p', '-vf', 'setsar=1'], logger=None)
            fallback_clip.close()
        else:
            cclip = ColorClip(size=(TARGET_W, TARGET_H), color=(30, 30, 30)).set_duration(scene_duration)
            cclip.write_videofile(norm_video_path, fps=24, codec="libx264", audio=False, preset="ultrafast", ffmpeg_params=['-pix_fmt', 'yuv420p', '-vf', 'setsar=1'], logger=None)
            cclip.close()

    try:
        vclip.close()
        z_clip.close()
        final_scene.close()
    except: pass
    
    video_files.append(os.path.abspath(norm_video_path))
    gc.collect()
    print(f"Scene {i+1} Ready: {keyword}")

# ==========================================
# DISK CONCATENATION (Merging Safely)
# ==========================================
with open("vid_list.txt", "w") as f:
    for vid in video_files: f.write(f"file '{vid}'\n")

with open("aud_list.txt", "w") as f:
    for aud in audio_files: f.write(f"file '{aud}'\n")

subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'vid_list.txt', '-c', 'copy', 'merged_video.mp4'], check=True)
subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', 'aud_list.txt', '-c', 'copy', 'merged_audio.wav'], check=True)

# --- Final Master Mix (Grade + BGM Ducking + Logo Overlay) ---
has_logo = os.path.exists("logo.png")
has_bgm = os.path.exists("bgm.mp3")

ffmpeg_cmd = ['ffmpeg', '-y', '-i', 'merged_video.mp4', '-i', 'merged_audio.wav']
filter_complex = ""
audio_map = ""
video_map = ""
inputs = 2

if has_bgm:
    ffmpeg_cmd.extend(['-stream_loop', '-1', '-i', 'bgm.mp3'])
    # BGM volume changed to 0.45 here as requested
    filter_complex += "[1:a]asplit=2[voice_main][voice_control]; [2:a]volume=0.45[bgm_low]; [bgm_low][voice_control]sidechaincompress=threshold=0.08:ratio=8:attack=200:release=1000[ducked_bgm]; [voice_main][ducked_bgm]amix=inputs=2:duration=first,loudnorm=I=-14:LRA=11:TP=-1.5[a_out]; "
    audio_map = "[a_out]"
    inputs += 1
else:
    filter_complex += "[1:a]loudnorm=I=-14:LRA=11:TP=-1.5[a_out]; "
    audio_map = "[a_out]"

channel_name = "Business Case Studies"
filter_complex += f"[0:v]eq=contrast=1.05:saturation=1.15,vignette,noise=alls=1:allf=t+u,drawtext=text='{channel_name}':fontcolor=white@0.5:fontsize=45:x=W-tw-50:y=H-th-50[v_graded]; "
current_v_map = "[v_graded]"

if has_logo:
    ffmpeg_cmd.extend(['-i', 'logo.png'])
    filter_complex += f"[{inputs-1}:v]format=rgba,colorchannelmixer=aa=0.85,scale=200:-1[logo]; {current_v_map}[logo]overlay=W-w-40:40[v_out]"
    video_map = "[v_out]"
else:
    video_map = current_v_map

if filter_complex.endswith("; "): filter_complex = filter_complex[:-2]
if filter_complex: ffmpeg_cmd.extend(['-filter_complex', filter_complex])

ffmpeg_cmd.extend([
    '-map', video_map, '-map', audio_map,
    '-c:v', 'libx264', '-preset', 'fast', '-profile:v', 'high', '-bf', '2', '-g', '48', '-crf', '26', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k', '-shortest', 'final_video.mp4'
])
print("Rendering Final Master Mix...")
subprocess.run(ffmpeg_cmd, check=True)

# ==========================================
# GITHUB RELEASES UPLOAD (NEW METHOD)
# ==========================================
video_link = None
print("\n🚀 Uploading Video directly to GitHub Releases...")

run_id = os.environ.get('GITHUB_RUN_ID', str(int(time.time())))
tag_name = f"vid-{run_id}"
repo_name = os.environ.get('GITHUB_REPOSITORY', "amu8085-lab/my-project1") 

try:
    cmd = ['gh', 'release', 'create', tag_name, 'final_video.mp4', '--repo', repo_name, '--notes', 'Automated Video Render']
    proc = subprocess.run(cmd, capture_output=True, text=True)
    
    if proc.returncode == 0:
        video_link = f"https://github.com/{repo_name}/releases/download/{tag_name}/final_video.mp4"
        print(f"✅ Success! Video uploaded to GitHub: {video_link}")
    else:
        err_msg = proc.stderr.strip()
        print(f"❌ GitHub Release failed. Error: {err_msg}")
except Exception as e:
    print(f"⚠️ Exception during GitHub upload: {str(e)}")

if not video_link:
    video_link = "Upload Failed"

# Telegram Notification (Bypassing n8n webhook)
safe_description = str(video_desc).replace('\n', '  ')
safe_title = str(video_title).replace('|', '')

if not chat_id or chat_id == "None":
    print("❌ Error: CHAT_ID is missing. Cannot send Telegram message.")
else:
    message_text = f"READY_TO_UPLOAD|{video_link}|{safe_title}|{thumbnail_prompt}|{safe_description}"
    if len(message_text) > 4000: message_text = message_text[:3990] + "...[TRUNC]"

    try:
        telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        response = requests.post(telegram_url, json={"chat_id": str(chat_id).strip(), "text": message_text})
        if response.status_code == 200:
            print(f"✅ Webhook bypassed! Sent video details directly to Telegram!")
        else:
            print(f"❌ Telegram alert failed! Status: {response.status_code}, Error: {response.text}")
    except Exception as e:
        print(f"❌ Failed to send Telegram alert: {e}")
