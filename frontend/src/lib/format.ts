const FPS = 12
const FRAMES_BASE = import.meta.env.FRAMES_BASE_URL ?? '/frames'

function frameUrl(episodeId: string, ms: number): string {
  return `${FRAMES_BASE}/${episodeId}/frame_${String(ms).padStart(8, '0')}.webp`
}

export function framePath(episodeId: string, startMs: number): string {
  const frameIndex = Math.round(startMs * FPS / 1000)
  const snappedMs = Math.floor(frameIndex * 1000 / FPS)
  return frameUrl(episodeId, snappedMs)
}

export function framesInRange(episodeId: string, startMs: number, endMs: number): string[] {
  const firstIndex = Math.ceil(startMs * FPS / 1000)
  const lastIndex = Math.floor(endMs * FPS / 1000)
  const paths: string[] = []
  for (let i = firstIndex; i <= lastIndex; i++) {
    const ms = Math.floor(i * 1000 / FPS)
    paths.push(frameUrl(episodeId, ms))
  }
  return paths
}

export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}
