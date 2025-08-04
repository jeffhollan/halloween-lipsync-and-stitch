import os
import subprocess
import re
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def stitch_videos(original_video_path=None, final_output_path=None, add_audio=True):
    """
    Stitch video chunks together with optional audio from original video.
    
    Args:
        original_video_path: Path to the original video for audio extraction (defaults to .env VIDEO_PATH)
        final_output_path: Path for the final output video (optional)
        add_audio: Whether to add audio from original video
    """
    # Load default video path from environment if not provided
    if original_video_path is None:
        original_video_path = os.getenv('VIDEO_PATH')
        if not original_video_path:
            raise ValueError("original_video_path not provided and VIDEO_PATH not found in .env file")
    
    # Settings
    output_dir = os.getenv('OUTPUT_DIR', '/home/jeffhollan/comfy/ComfyUI/output/')  # Where chunks are saved
    
    # Generate default output filename if not provided
    if final_output_path is None:
        base_name = os.path.splitext(os.path.basename(original_video_path))[0]
        final_output_path = os.path.join(output_dir, f'{base_name}_combined.mp4')
    
    temp_concat_file = os.path.join(output_dir, 'chunks.txt')
    temp_audio_file = os.path.join(output_dir, 'temp_audio.aac') if add_audio else None

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

    # Step 3: Concat videos (lossless) - remove existing file if it exists
    temp_output = final_output_path + '.temp.mp4'
    if os.path.exists(temp_output):
        os.remove(temp_output)
    
    concat_cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', temp_concat_file,
        '-c', 'copy',
        '-y',  # Overwrite without prompt
        temp_output
    ]
    subprocess.run(concat_cmd, check=True)

    # Step 4: Optionally add audio
    if add_audio:
        # Remove existing temp audio file if it exists
        if temp_audio_file and os.path.exists(temp_audio_file):
            os.remove(temp_audio_file)
        
        # Extract audio from original (full duration)
        extract_audio_cmd = [
            'ffmpeg',
            '-i', original_video_path,
            '-vn',  # No video
            '-c:a', 'copy',
            '-y',  # Overwrite without prompt
            temp_audio_file
        ]
        subprocess.run(extract_audio_cmd, check=True)
        
        # Remove existing final output file if it exists
        if os.path.exists(final_output_path):
            os.remove(final_output_path)
        
        # Mux audio into concat video (trim audio to match video duration if needed)
        mux_cmd = [
            'ffmpeg',
            '-i', temp_output,
            '-i', temp_audio_file,
            '-c', 'copy',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-shortest',  # Trim to shortest (in case durations mismatch)
            '-y',  # Overwrite without prompt
            final_output_path
        ]
        subprocess.run(mux_cmd, check=True)
        
        # Clean up temp audio
        os.remove(temp_audio_file)
    else:
        # Remove existing final output file if it exists
        if os.path.exists(final_output_path):
            os.remove(final_output_path)
        os.rename(temp_output, final_output_path)

    # Clean up
    os.remove(temp_concat_file)
    if os.path.exists(temp_output):
        os.remove(temp_output)

    print(f"Stitching complete! Final video: {final_output_path}")
    return final_output_path

# Main execution when script is run directly
if __name__ == "__main__":
    # Load environment variables for defaults
    default_video = os.getenv('VIDEO_PATH', '/home/jeffhollan/comfy/ComfyUI/input/Kyla_Thriller.mp4')
    output_dir = os.getenv('OUTPUT_DIR', '/home/jeffhollan/comfy/ComfyUI/output/')
    
    original_video = default_video
    final_output = os.path.join(output_dir, 'final_animated_video.mp4')
    
    # Allow command line arguments to override
    if len(sys.argv) > 1:
        original_video = sys.argv[1]
    if len(sys.argv) > 2:
        final_output = sys.argv[2]
    
    stitch_videos(original_video, final_output, add_audio=True)