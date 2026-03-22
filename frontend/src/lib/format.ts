export function padFrameNumber(frame: number): string {
  return String(frame).padStart(6, '0')
}

export function framePath(episodeId: string, frame: number): string {
  return `/frames/${episodeId}/frame_${padFrameNumber(frame)}.webp`
}

export function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}
