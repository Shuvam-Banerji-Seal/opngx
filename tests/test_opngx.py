

def test_video_render_and_framecount(fixture_dir):
    """MP4 render pipes LUT-mapped frames through ffmpeg (needs ffmpeg)."""
    import shutil
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    out = fixture_dir / "clip.mp4"
    st = opngx.render_video(str(fixture_dir / "cam_9.9" / "cam_9.9.bin"),
                            str(out), mode="reference",
                            start=0, count=20, fps=10, crf=30)
    assert st["frames_written"] == 20
    assert out.stat().st_size > 2048
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True)
    assert r.stdout.strip() == "20"
