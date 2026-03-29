import { useState, useCallback, useEffect } from 'preact/hooks'

export default function NavSearch() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const q = params.get('q')
    if (q) setQuery(q)
  }, [])

  const handleInput = useCallback((e: Event) => {
    const value = (e.target as HTMLInputElement).value
    setQuery(value)
    window.dispatchEvent(new CustomEvent('nav-search', { detail: value }))
  }, [])

  const handleSubmit = useCallback(
    (e: Event) => {
      e.preventDefault()
      if (query.trim()) {
        window.location.href = `/?q=${encodeURIComponent(query.trim())}`
      }
    },
    [query],
  )

  const handleRandom = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/random')
      const data = await res.json()
      if (data.episodeId && data.startMs != null) {
        window.location.href = `/frame/${data.episodeId}/${data.startMs}`
      }
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  return (
    <form class="flex items-center gap-2 flex-1" onSubmit={handleSubmit}>
      <div class="relative flex-1">
        <input
          type="text"
          value={query}
          onInput={handleInput}
          placeholder="Buscar una frase..."
          autofocus
          class="w-full px-4 py-2 text-base border-2 border-ink rounded-full outline-none focus:border-ink bg-white"
        />
        {loading && (
          <div
            class="absolute right-4 top-1/2 -translate-y-1/2 w-2.5 h-2.5 bg-ink rounded-full"
            style="animation: pulse-dot 0.8s ease-in-out infinite"
          />
        )}
      </div>
      <button
        type="button"
        onClick={handleRandom}
        class="shrink-0 px-4 py-2 bg-ink text-primary font-semibold rounded-full border-2 border-ink hover:bg-transparent hover:text-ink"
        title="Frase al azar"
      >
        Al azar
      </button>
    </form>
  )
}
