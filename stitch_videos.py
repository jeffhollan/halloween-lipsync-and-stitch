import os
import subprocess
import re

# Settings (adjust as needed)
output_dir = '/home/jeffhollan/comfy/ComfyUI/output/'  # Where chunks are saved
original_video = '/home/jeffhollan/comfy/ComfyUI/scripts/thriller_test.mkv'  # For audio extraction
final_output = os.path.join(output_dir, 'final_animated_video.mp4')
add_audio = True  # Set to False if no audio needed
temp_concat_file = os.path.join(output_dir, 'chunks.txt')
temp_audio_file = os.path.join(output_dir, 'temp_audio.aac') if add_audio else None  # Changed to .aac for AAC codec compatibility

# Step 1: Find and sort chunk MP4 files
chunk_files = {}
for file in os.listdir(output_dir):
    if file.startswith('AdvancedLivePortrait_chunk_') and file.endswith('.mp4'):
        match = re.match(r'AdvancedLivePortrait_chunk_(\d+)_(\d+)\.mp4', file)
        if match:
            chunk_num = int(match.group(1))
            suffix = int(match.group(2))
            full_path = os.path.join(output_dir, file)
            # Keep the highest suffix (latest run) per chunk
            if chunk_num not in chunk_files or suffix > chunk_files[chunk_num][1]:
                chunk_files[chunk_num] = (full_path, suffix)

# Sort by chunk number and get list of paths
sorted_chunks = [chunk_files[num][0] for num in sorted(chunk_files.keys())]
print(f"Found {len(sorted_chunks)} chunks: {sorted_chunks}")

if not sorted_chunks:
    raise ValueError("No chunk MP4 files found!")

# Step 2: Create concat list file
with open(temp_concat_file, 'w') as f:
    for chunk in sorted_chunks:
        f.write(f"file '{chunk}'\n")

# Step 3: Concat videos (lossless)
concat_cmd = [
    'ffmpeg',
    '-f', 'concat',
    '-safe', '0',
    '-i', temp_concat_file,
    '-c', 'copy',
    final_output + '.temp.mp4'  # Temp to avoid overwrite issues
]
subprocess.run(concat_cmd, check=True)

# Step 4: Optionally add audio
if add_audio:
    # Extract audio from original (full duration)
    extract_audio_cmd = [
        'ffmpeg',
        '-i', original_video,
        '-vn',  # No video
        '-c:a', 'copy',
        temp_audio_file
    ]
    subprocess.run(extract_audio_cmd, check=True)
    
    # Mux audio into concat video (trim audio to match video duration if needed)
    mux_cmd = [
        'ffmpeg',
        '-i', final_output + '.temp.mp4',
        '-i', temp_audio_file,
        '-c', 'copy',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-shortest',  # Trim to shortest (in case durations mismatch)
        final_output
    ]
    subprocess.run(mux_cmd, check=True)
    
    # Clean up temp audio
    os.remove(temp_audio_file)
else:
    os.rename(final_output + '.temp.mp4', final_output)

# Clean up
os.remove(temp_concat_file)
os.remove(final_output + '.temp.mp4') if os.path.exists(final_output + '.temp.mp4') else None

print(f"Stitching complete! Final video: {final_output}")