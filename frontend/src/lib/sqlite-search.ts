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

    let rows: any[]

    try {
      rows = this.db.prepare(`
        SELECT s.episode_id, s.text, s.start_ms, s.end_ms,
               e.season, e.episode, e.title
        FROM subtitles_fts fts
        JOIN subtitles s ON s.id = fts.rowid
        JOIN episodes e ON e.id = s.episode_id
        WHERE subtitles_fts MATCH ?
        ORDER BY bm25(subtitles_fts)
        LIMIT ?
      `).all(sanitized, limit)
    } catch {
      rows = []
    }

    if (rows.length === 0) {
      const likePattern = `%${query.trim()}%`
      rows = this.db.prepare(`
        SELECT s.episode_id, s.text, s.start_ms, s.end_ms,
               e.season, e.episode, e.title
        FROM subtitles s
        JOIN episodes e ON e.id = s.episode_id
        WHERE s.text LIKE ?
        LIMIT ?
      `).all(likePattern, limit)
    }

    return rows.map((row) => ({
      episodeId: row.episode_id,
      startMs: row.start_ms,
      text: row.text,
      season: row.season,
      episode: row.episode,
      episodeTitle: row.title ?? '',
    }))
  }

  async getRandomFrame(): Promise<SearchResult | null> {
    const row = this.db.prepare(`
      SELECT s.episode_id, s.text, s.start_ms,
             e.season, e.episode, e.title
      FROM subtitles s
      JOIN episodes e ON e.id = s.episode_id
      ORDER BY RANDOM()
      LIMIT 1
    `).get() as any

    if (!row) return null

    return {
      episodeId: row.episode_id,
      startMs: row.start_ms,
      text: row.text,
      season: row.season,
      episode: row.episode,
      episodeTitle: row.title ?? '',
    }
  }

  async getFrameDetail(episodeId: string, startMs: number): Promise<FrameDetail | null> {
    const row = this.db.prepare(`
      SELECT s.text, s.start_ms, s.end_ms,
             e.season, e.episode, e.title
      FROM subtitles s
      JOIN episodes e ON e.id = s.episode_id
      WHERE s.episode_id = ?
        AND s.start_ms = ?
      LIMIT 1
    `).get(episodeId, startMs) as any

    if (!row) return null

    return {
      episodeId,
      startMs: row.start_ms,
      endMs: row.end_ms,
      text: row.text,
      season: row.season,
      episode: row.episode,
      episodeTitle: row.title ?? '',
    }
  }
}

function sanitizeQuery(query: string): string {
  const trimmed = query.trim()
  if (!trimmed) return ''

  const tokens = trimmed.split(/\s+/)
  return tokens
    .map((token) => token.replace(/"/g, ''))
    .filter(Boolean)
    .map((token) => `"${token}"*`)
    .join(' ')
}
