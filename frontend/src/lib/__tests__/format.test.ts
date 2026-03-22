import { describe, it, expect } from 'vitest'
import { padFrameNumber, framePath, formatTimestamp } from '../format'

describe('padFrameNumber', () => {
  it('pads single digit to 6 chars', () => {
    expect(padFrameNumber(1)).toBe('000001')
  })

  it('pads multi-digit number', () => {
    expect(padFrameNumber(123)).toBe('000123')
  })

  it('does not pad 6-digit number', () => {
    expect(padFrameNumber(999999)).toBe('999999')
  })
})

describe('framePath', () => {
  it('builds correct path', () => {
    expect(framePath('S05E05', 123)).toBe('/frames/S05E05/frame_000123.webp')
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
