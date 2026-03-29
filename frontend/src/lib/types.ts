export interface SearchResult {
  episodeId: string
  startMs: number
  text: string
  season: number
  episode: number
  episodeTitle: string
}

export interface FrameDetail {
  episodeId: string
  startMs: number
  endMs: number
  text: string
  season: number
  episode: number
  episodeTitle: string
}

export interface SearchService {
  search(query: string, limit: number): Promise<SearchResult[]>
  getFrameDetail(episodeId: string, startMs: number): Promise<FrameDetail | null>
  getRandomFrame(): Promise<SearchResult | null>
}
