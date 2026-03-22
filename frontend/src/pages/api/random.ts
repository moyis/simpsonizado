import type { APIRoute } from 'astro'
import { createSearchService } from '../../lib/search-factory'

export const prerender = false

export const GET: APIRoute = async () => {
  try {
    const service = createSearchService()
    const result = await service.getRandomFrame()

    if (!result) {
      return new Response(JSON.stringify({ error: 'No frames found' }), {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      })
    }

    return new Response(JSON.stringify(result), {
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (error) {
    console.error('Random frame error:', error)
    return new Response(JSON.stringify({ error: 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    })
  }
}
