import json
import requests
import math
import subprocess
import time
import os
from dotenv import load_dotenv
from stitch_videos import stitch_videos

# Load environment variables
load_dotenv()

# ComfyUI API endpoints (adjust if not localhost)
comfy_prompt_url = 'http://127.0.0.1:8188/prompt'
comfy_history_url = 'http://127.0.0.1:8188/history'

# Load your API-format workflow JSON (replace with your actual API JSON file path)
with open('puppet_bust_api.json', 'r') as f:
    workflow = json.load(f)

# Get video path from environment variable
video_path = os.getenv('VIDEO_PATH')
if not video_path:
    raise ValueError("VIDEO_PATH not found in .env file")

# Update the reference image in the workflow from environment variable
reference_image = os.getenv('REFERENCE_IMAGE')
if reference_image:
    workflow['3']['inputs']['image'] = reference_image
else:
    print("Warning: REFERENCE_IMAGE not found in .env file, using default from JSON")

# Use ffprobe to get video info (requires FFmpeg installed)
def get_video_info(path):
    # Get frame count
    cmd_count = [
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'v:0',
        '-count_frames',
        '-show_entries', 'stream=nb_read_frames',
        '-of', 'csv=p=0',
        path
    ]
    result_count = subprocess.run(cmd_count, capture_output=True, text=True)
    if result_count.returncode != 0:
        raise ValueError(f"Error getting frame count: {result_count.stderr}")
    frame_count_str = result_count.stdout.strip()
    if not frame_count_str.isdigit():
        raise ValueError(f"Invalid frame count: {frame_count_str}")
    frame_count = int(frame_count_str)
    
    # Get FPS
    cmd_fps = [
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        path
    ]
    result_fps = subprocess.run(cmd_fps, capture_output=True, text=True)
    if result_fps.returncode != 0:
        raise ValueError(f"Error getting FPS: {result_fps.stderr}")
    fps_frac = result_fps.stdout.strip()
    fps = eval(fps_frac)  # Convert '30/1' to 30.0
    
    return frame_count, fps

total_frames, fps = get_video_info(video_path)
print(f"Video info: Total frames = {total_frames}, FPS = {fps}")

# Chunk settings (reduced for safety)
chunk_seconds = 8  # Start small to avoid OOM; increase if stable
chunk_frames = math.ceil(chunk_seconds * fps)

# Calculate number of chunks
num_chunks = math.ceil(total_frames / chunk_frames)

# Base motion sequence from your command (motion_index, change_frames, wait_frames)
base_sequence = [
    (1, 1, 10),
    (2, 5, 10),
    (0, 2, 50),
    (1, 2, 0)
]

# Calculate cycle length for looping
cycle_length = sum(change + wait for _, change, wait in base_sequence)

# Function to generate command string for a chunk (continues sequence seamlessly)
def generate_command(global_start, num_frames):
    adjusted_steps = []
    remaining = num_frames
    pos = global_start % cycle_length  # Starting position in the cycle
    
    while remaining > 0:
        cumulative = 0
        for motion, change, wait in base_sequence:
            step_total = change + wait
            if pos >= cumulative and pos < cumulative + step_total:
                # Adjust for mid-step start
                pos_in_step = pos - cumulative
                if pos_in_step < change:
                    eff_change = change - pos_in_step
                    eff_wait = wait
                else:
                    eff_change = 0
                    eff_wait = wait - (pos_in_step - change)
                if eff_change > 0 or eff_wait > 0:
                    # Trim to remaining frames if needed
                    step_frames = eff_change + eff_wait
                    if step_frames > remaining:
                        # Proportionally trim (prioritize change phase)
                        if eff_change >= remaining:
                            eff_change = remaining
                            eff_wait = 0
                        else:
                            eff_wait = remaining - eff_change
                    adjusted_steps.append((motion, eff_change, eff_wait))
                    remaining -= (eff_change + eff_wait)
                pos = cumulative + step_total  # Move to next step
                if remaining <= 0:
                    break
            elif pos < cumulative:
                # Full step
                step_frames = change + wait
                if step_frames > remaining:
                    # Trim last step
                    if change >= remaining:
                        change = remaining
                        wait = 0
                    else:
                        wait = remaining - change
                adjusted_steps.append((motion, change, wait))
                remaining -= (change + wait)
                if remaining <= 0:
                    break
            cumulative += step_total
        pos = 0  # Loop back if needed
    
    # Format as multiline string (skip zero-duration steps)
    command_str = '\n'.join(f"{motion} = {change}:{wait}" for motion, change, wait in adjusted_steps if change > 0 or wait > 0)
    return command_str

# Function to wait for prompt completion (polls /history)
def wait_for_completion(prompt_id, max_wait_seconds=600, poll_interval=10):
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        response = requests.get(comfy_history_url)
        history = response.json()
        if prompt_id in history:
            print(f"History for {prompt_id}: {json.dumps(history[prompt_id], indent=2)}")  # Log details for debugging
            return True
        time.sleep(poll_interval)
    raise TimeoutError(f"Prompt {prompt_id} did not complete in {max_wait_seconds} seconds")

for chunk_id in range(num_chunks):
    skip = chunk_id * chunk_frames
    cap = min(chunk_frames, total_frames - skip)
    
    # Generate dynamic command for this chunk
    dynamic_command = generate_command(skip, cap)
    
    # Modify AdvancedLivePortrait (node ID '7') with dynamic command
    workflow['7']['inputs']['command'] = dynamic_command
    workflow['7']['inputs']['turn_on'] = dynamic_command
    workflow['7']['inputs']['tracking_src_vid'] = dynamic_command
    
    # Modify VHS_LoadVideo (node ID '9')
    workflow['9']['inputs']['skip_first_frames'] = skip
    workflow['9']['inputs']['frame_load_cap'] = cap
    workflow['9']['inputs']['select_every_nth'] = 1  # Full frames; adjust if needed (original was 2)
    workflow['9']['inputs']['custom_width'] = 1280  # Downsize to 1280x720; adjust as needed (0 disables)
    workflow['9']['inputs']['custom_height'] = 720
    
    # Modify VHS_VideoCombine (node ID '10') for unique filename and FPS
    workflow['10']['inputs']['filename_prefix'] = f'AdvancedLivePortrait_chunk_{chunk_id}'
    workflow['10']['inputs']['frame_rate'] = fps  # Set to match original FPS
    
    # Queue the prompt and get prompt_id
    response = requests.post(comfy_prompt_url, json={'prompt': workflow})
    if response.status_code != 200:
        print(f"Error queuing chunk {chunk_id}: {response.text}")
        continue
    data = response.json()
    prompt_id = data.get('prompt_id')
    print(f'Queued chunk {chunk_id} with prompt_id: {prompt_id}')
    
    # Wait for this chunk to complete before queuing the next
    try:
        wait_for_completion(prompt_id)
        print(f'Chunk {chunk_id} completed.')
    except TimeoutError as e:
        print(e)
        print("Likely crash—check ComfyUI console. Skipping to next chunk.")
        # Continue or break as needed

print("All chunks processed. Starting video stitching...")

# Extract the base name from the video path for the final output
base_name = os.path.splitext(os.path.basename(video_path))[0]
output_dir = os.getenv('OUTPUT_DIR', '/home/jeffhollan/comfy/ComfyUI/output/')
final_output_path = os.path.join(output_dir, f'{base_name}_combined.mp4')

# Stitch all the chunks together
try:
    final_video = stitch_videos(video_path, final_output_path, add_audio=True)
    print(f"Video processing complete! Final output: {final_video}")
except Exception as e:
    print(f"Error during video stitching: {e}")
    print("Individual chunks are still available in the output directory.")