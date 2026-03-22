import { describe, it, expect, beforeAll } from 'vitest'
import { SqliteSearchService } from '../sqlite-search'
import { resolve } from 'path'

const DB_PATH = resolve(__dirname, '../../../../data/simpsonizado.db')

describe('SqliteSearchService', () => {
  let service: SqliteSearchService

  beforeAll(() => {
    service = new SqliteSearchService(DB_PATH)
  })

  describe('search', () => {
    it('returns results for a known word', async () => {
      const results = await service.search('homero', 5)
      expect(results.length).toBeGreaterThan(0)
      expect(results[0]).toHaveProperty('episodeId')
      expect(results[0]).toHaveProperty('frame')
      expect(results[0]).toHaveProperty('text')
      expect(results[0]).toHaveProperty('season')
      expect(results[0]).toHaveProperty('episode')
      expect(results[0]).toHaveProperty('episodeTitle')
      expect(results[0]).toHaveProperty('startMs')
    })

    it('returns empty array for empty query', async () => {
      const results = await service.search('', 20)
      expect(results).toEqual([])
    })

    it('returns empty array for whitespace-only query', async () => {
      const results = await service.search('   ', 20)
      expect(results).toEqual([])
    })

    it('handles FTS5 special characters without crashing', async () => {
      const results = await service.search('"AND" OR NOT *', 20)
      expect(Array.isArray(results)).toBe(true)
    })

    it('respects limit parameter', async () => {
      const results = await service.search('homero', 1)
      expect(results.length).toBe(1)
    })

    it('computes mid-frame correctly', async () => {
      const results = await service.search('homero', 1)
      expect(results.length).toBe(1)
      expect(results[0].frame).toBeGreaterThan(0)
    })

    it('pads results when fewer than limit', async () => {
      const results = await service.search('cementerio', 20)
      expect(results.length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('getFrameDetail', () => {
    it('returns detail for a valid frame within a subtitle range', async () => {
      const searchResults = await service.search('homero', 1)
      expect(searchResults.length).toBe(1)

      const detail = await service.getFrameDetail(
        searchResults[0].episodeId,
        searchResults[0].frame,
      )
      expect(detail).not.toBeNull()
      expect(detail!.text).toBe(searchResults[0].text)
      expect(detail!.startFrame).toBeLessThanOrEqual(detail!.frame)
      expect(detail!.endFrame).toBeGreaterThanOrEqual(detail!.frame)
    })

    it('returns null for non-existent episode', async () => {
      const detail = await service.getFrameDetail('S99E99', 1)
      expect(detail).toBeNull()
    })

    it('returns null for frame out of range', async () => {
      const detail = await service.getFrameDetail('S05E05', 999999)
      expect(detail).toBeNull()
    })
  })
})
