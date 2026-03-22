import Database from 'better-sqlite3'
import type { SearchResult, FrameDetail, SearchService } from './types'

export class SqliteSearchService implements SearchService {
  private readonly db: Database.Database

  constructor(dbPath: string) {
    this.db = new Database(dbPath, { readonly: true })
    this.db.pragma('journal_mode = WAL')
  }

  async search(query: string, limit: number): Promise<SearchResult[]> {
    const sanitized = sanitizeQuery(query)
    if (!sanitized) return []

    const stmt = this.db.prepare(`
      SELECT s.episode_id, s.text, s.start_ms, s.end_ms,
             s.start_frame, s.end_frame,
             e.season, e.episode, e.title
      FROM subtitles_fts fts
      JOIN subtitles s ON s.id = fts.rowid
      JOIN episodes e ON e.id = s.episode_id
      WHERE subtitles_fts MATCH ?
      ORDER BY bm25(subtitles_fts)
      LIMIT ?
    `)

    let rows: any[]
    try {
      rows = stmt.all(sanitized, limit)
    } catch {
      return []
    }

    const results: SearchResult[] = rows.map((row) => ({
      episodeId: row.episode_id,
      frame: Math.floor((row.start_frame + row.end_frame) / 2),
      text: row.text,
      season: row.season,
      episode: row.episode,
      episodeTitle: row.title ?? '',
      startMs: row.start_ms,
    }))

    if (results.length < limit) {
      return padResults(results, rows, limit)
    }

    return results
  }

  async getRandomFrame(): Promise<SearchResult | null> {
    const row = this.db.prepare(`
      SELECT s.episode_id, s.text, s.start_ms, s.start_frame, s.end_frame,
             e.season, e.episode, e.title
      FROM subtitles s
      JOIN episodes e ON e.id = s.episode_id
      ORDER BY RANDOM()
      LIMIT 1
    `).get() as any

    if (!row) return null

    return {
      episodeId: row.episode_id,
      frame: Math.floor((row.start_frame + row.end_frame) / 2),
      text: row.text,
      season: row.season,
      episode: row.episode,
      episodeTitle: row.title ?? '',
      startMs: row.start_ms,
    }
  }

  async getFrameDetail(episodeId: string, frame: number): Promise<FrameDetail | null> {
    const stmt = this.db.prepare(`
      SELECT s.text, s.start_ms, s.end_ms, s.start_frame, s.end_frame,
             e.season, e.episode, e.title
      FROM subtitles s
      JOIN episodes e ON e.id = s.episode_id
      WHERE s.episode_id = ?
        AND s.start_frame <= ?
        AND s.end_frame >= ?
      LIMIT 1
    `)

    const row = stmt.get(episodeId, frame, frame) as any
    if (!row) return null

    return {
      episodeId,
      frame,
      text: row.text,
      season: row.season,
      episode: row.episode,
      episodeTitle: row.title ?? '',
      startMs: row.start_ms,
      endMs: row.end_ms,
      startFrame: row.start_frame,
      endFrame: row.end_frame,
    }
  }
}

function sanitizeQuery(query: string): string {
  const trimmed = query.trim()
  if (!trimmed) return ''

  const tokens = trimmed.split(/\s+/)
  return tokens.map((token) => `"${token.replace(/"/g, '')}"`).join(' ')
}

function padResults(
  results: SearchResult[],
  rows: any[],
  limit: number,
): SearchResult[] {
  const seen = new Set(results.map((r) => `${r.episodeId}:${r.frame}`))
  const padded = [...results]

  for (const row of rows) {
    if (padded.length >= limit) break

    const midFrame = Math.floor((row.start_frame + row.end_frame) / 2)
    const offsets = [-1, 1, -2, 2]

    for (const offset of offsets) {
      if (padded.length >= limit) break

      const neighborFrame = midFrame + offset
      if (neighborFrame < row.start_frame || neighborFrame > row.end_frame) continue

      const key = `${row.episode_id}:${neighborFrame}`
      if (seen.has(key)) continue

      seen.add(key)
      padded.push({
        episodeId: row.episode_id,
        frame: neighborFrame,
        text: row.text,
        season: row.season,
        episode: row.episode,
        episodeTitle: row.title ?? '',
        startMs: row.start_ms,
      })
    }
  }

  return padded
}
