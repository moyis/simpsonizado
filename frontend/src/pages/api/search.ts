import type { APIRoute } from 'astro'
import { createSearchService } from '../../lib/search-factory'

export const prerender = false

export const GET: APIRoute = async ({ url }) => {
  const query = url.searchParams.get('q') ?? ''
  const limitParam = url.searchParams.get('limit')

  if (!query.trim()) {
    return new Response(JSON.stringify({ results: [] }), {
      headers: { 'Content-Type': 'application/json' },
    })
  }

  const limit = Math.min(Math.max(parseInt(limitParam ?? '20', 10) || 20, 1), 50)

  try {
    const service = createSearchService()
    const results = await service.search(query, limit)
    return new Response(JSON.stringify({ results }), {
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (error) {
    console.error('Search error:', error)
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
