export interface SearchResult {
  episodeId: string
  frame: number
  text: string
  season: number
  episode: number
  episodeTitle: string
  startMs: number
}

export interface FrameDetail {
  episodeId: string
  frame: number
  text: string
  season: number
  episode: number
  episodeTitle: string
  startMs: number
  endMs: number
  startFrame: number
  endFrame: number
}

export interface SearchService {
  search(query: string, limit: number): Promise<SearchResult[]>
  getFrameDetail(episodeId: string, frame: number): Promise<FrameDetail | null>
  getRandomFrame(): Promise<SearchResult | null>
}
