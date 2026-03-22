import type { SearchService } from './types'
import { SqliteSearchService } from './sqlite-search'

let instance: SearchService | null = null

export function createSearchService(): SearchService {
  if (!instance) {
    const dbPath = import.meta.env.DATABASE_PATH ?? '../data/simpsonizado.db'
    instance = new SqliteSearchService(dbPath)
  }
  return instance
}
