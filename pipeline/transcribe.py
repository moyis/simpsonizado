from __future__ import annotations

import argparse
import logging
import os
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed

from pipeline import transcriber
from pipeline.extract import parse_episode_id
from pipeline.srt_cleaner import clean_srt
from pipeline.transcriber import load_model, segments_to_srt

logger = logging.getLogger(__name__)

MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]

_worker_model = None


def _init_worker(model_size: str) -> None:
    global _worker_model
    _worker_model = load_model(model_size)


def _process_episode_worker(args: tuple) -> bool:
    input_path, output_dir, force = args
    return process_single_episode(input_path, output_dir, _worker_model, force)


def process_single_episode(
    input_path: str,
    output_dir: str,
    model: object,
    force: bool = False,
) -> bool:
    episode_id = parse_episode_id(os.path.basename(input_path))
    if episode_id is None:
        logger.error("Could not parse episode ID from %s", input_path)
        return False

    srt_output_path = os.path.join(output_dir, f"{episode_id}.srt")

    if not force and os.path.exists(srt_output_path):
        logger.info("[%s] SRT already exists, skipping.", episode_id)
        return True

    try:
        logger.info("[%s] Finding Spanish audio track...", episode_id)
        audio_track = transcriber.find_spanish_audio_track(input_path)
        if audio_track is None:
            logger.error("[%s] No Spanish audio track found.", episode_id)
            return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = os.path.join(tmp_dir, f"{episode_id}.wav")

            logger.info("[%s] Extracting audio to WAV...", episode_id)
            transcriber.extract_audio(input_path, audio_track, wav_path)

            logger.info("[%s] Transcribing audio...", episode_id)
            segments = transcriber.transcribe_audio(wav_path, model)

        logger.info(
            "[%s] Cleaning %d segments...", episode_id, len(segments)
        )
        segments = clean_srt(segments)

        logger.info(
            "[%s] Writing %d segments to SRT...", episode_id, len(segments)
        )
        segments_to_srt(segments, srt_output_path)

        logger.info("[%s] Done.", episode_id)
        return True

    except MemoryError:
        logger.error(
            "[%s] Out of memory. Try reducing --workers or using a smaller --model.",
            episode_id,
        )
        return False
    except Exception:
        logger.exception("[%s] Failed to process episode.", episode_id)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe Simpsons episodes using Whisper"
    )
    parser.add_argument("--input", help="Path to a single .mkv file")
    parser.add_argument("--input-dir", help="Path to directory of .mkv files")
    parser.add_argument(
        "--output-dir",
        default="data/whisper_srt",
        help="Output directory for SRT files (default: data/whisper_srt)",
    )
    parser.add_argument(
        "--model",
        choices=MODEL_CHOICES,
        default="large-v3",
        help="Whisper model size (default: large-v3)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1). "
        "GPU acceleration makes single worker optimal in most cases.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-process existing SRT files",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.input and not args.input_dir:
        parser.error("Either --input or --input-dir is required")

    if args.input and args.input_dir:
        parser.error("Cannot use both --input and --input-dir")

    os.makedirs(args.output_dir, exist_ok=True)

    if args.workers > 1:
        logger.warning(
            "Using %d workers with GPU-accelerated mlx-whisper. "
            "Multiple workers share the GPU and may not improve throughput.",
            args.workers,
        )

    if args.input:
        model = load_model(args.model)
        process_single_episode(
            args.input, args.output_dir, model, args.force
        )
    else:
        mkv_files = sorted(
            f for f in os.listdir(args.input_dir) if f.endswith(".mkv")
        )
        episodes = []
        for filename in mkv_files:
            episode_id = parse_episode_id(filename)
            if episode_id is None:
                logger.warning(
                    "Skipping %s: could not parse episode ID", filename
                )
                continue
            episodes.append(os.path.join(args.input_dir, filename))

        if not episodes:
            logger.warning("No .mkv files found in %s", args.input_dir)
            return

        succeeded = 0
        failed = 0

        if args.workers <= 1:
            model = load_model(args.model)
            for input_path in episodes:
                if process_single_episode(
                    input_path, args.output_dir, model, args.force
                ):
                    succeeded += 1
                else:
                    failed += 1
        else:
            workers = min(args.workers, len(episodes))
            with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_init_worker,
                initargs=(args.model,),
            ) as executor:
                futures = {
                    executor.submit(
                        _process_episode_worker,
                        (input_path, args.output_dir, args.force),
                    ): input_path
                    for input_path in episodes
                }
                for future in as_completed(futures):
                    if future.result():
                        succeeded += 1
                    else:
                        failed += 1

        logger.info(
            "Batch complete: %d succeeded, %d failed", succeeded, failed
        )


if __name__ == "__main__":
    main()
