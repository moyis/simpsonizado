import { describe, it, expect } from 'vitest'
import { framePath, formatTimestamp } from '../format'

describe('framePath', () => {
  it('snaps to nearest 12fps frame', () => {
    // 1000ms = frame 12, snapped = 1000ms
    expect(framePath('S05E05', 1000)).toBe('/frames/S05E05/frame_00001000.webp')
  })

  it('snaps small timestamps to nearest frame', () => {
    // 500ms -> frame 6 -> 6*1000/12 = 500ms
    expect(framePath('S01E01', 500)).toBe('/frames/S01E01/frame_00000500.webp')
  })

  it('snaps arbitrary timestamps to nearest frame', () => {
    // 405440ms -> frame 4865.28 -> round to 4865 -> floor(4865*1000/12) = 405416ms
    expect(framePath('S04E12', 405440)).toBe('/frames/S04E12/frame_00405416.webp')
  })

  it('snaps to frame 0 for 0ms', () => {
    expect(framePath('S01E01', 0)).toBe('/frames/S01E01/frame_00000000.webp')
  })
})

describe('formatTimestamp', () => {
  it('formats zero milliseconds', () => {
    expect(formatTimestamp(0)).toBe('0:00')
  })

  it('formats seconds only', () => {
    expect(formatTimestamp(5000)).toBe('0:05')
  })

  it('formats minutes and seconds', () => {
    expect(formatTimestamp(125000)).toBe('2:05')
  })

  it('pads seconds to two digits', () => {
    expect(formatTimestamp(61000)).toBe('1:01')
  })
})
