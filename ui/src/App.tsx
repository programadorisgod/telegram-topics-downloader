import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'

type Hit = { msg_id: number; text: string; topic_id: number; links?: string[] }
type TopicResult = {
  topic_title: string
  topic_id: number
  folder: string
  hits: Hit[]
}
type SearchResponse = { query: string; count: number; results: TopicResult[] }
type AskResponse =
  | { query: string; cached: boolean; topics: TopicResult[]; answer: string; error?: never; ia_activa?: true }
  | { query: string; ia_activa: false; error: string; topics: TopicResult[] }
  | { error: string }

export default function App() {
  const [q, setQ] = useState('')
  const [search, setSearch] = useState<SearchResponse | null>(null)
  const [ask, setAsk] = useState<AskResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [checking, setChecking] = useState(true)
  const [syncStatus, setSyncStatus] = useState<{ state: string; detail: string } | null>(null)
  // chequeo inicial de sesión
  useEffect(() => {
    fetch('/api/auth/status')
      .then(r => r.json())
      .then(d => {
        if (d.authorized) setReady(true)
      })
      .catch(() => {})
      .finally(() => setChecking(false))
  }, [])

  // poll /api/status cada 3s: muestra banner de progreso y setea ready cuando arranca listen
  useEffect(() => {
    const id = setInterval(() => {
      fetch('/api/status')
        .then(r => r.json())
        .then(d => {
          setSyncStatus(d)
          if (d.state === 'listening') setReady(true)
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(id)
  }, [])

  async function run(query: string) {
    if (!query.trim() || loading) return
    setLoading(true)
    setError(null)
    setSearch(null)
    setAsk(null)
    try {
      const [sr, ar] = await Promise.all([
        fetch(`/api/search?q=${encodeURIComponent(query)}`).then(r => r.json()),
        fetch('/api/ask', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ query }),
        }).then(r => r.json()),
      ])
      setSearch(sr)
      setAsk(ar)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto max-w-3xl px-4 py-12">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight">knw</h1>
          <p className="text-sm text-zinc-400">recursos de desarrollo, buscados con IA sobre tu base de topics</p>
        </header>

        <form
          onSubmit={e => {
            e.preventDefault()
            run(q)
          }}
          className="mb-8"
        >
          <div className="flex gap-2">
            <input
              value={q}
              onChange={e => setQ(e.target.value)}
              placeholder='probá "kubernetes", "api vibrar dispositivo", "recursos gratis para devs"...'
              className="w-full rounded-lg border border-zinc-700 bg-zinc-900 px-4 py-3 text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={loading || !ready}
              className="shrink-0 rounded-lg bg-zinc-100 px-5 py-3 font-medium text-zinc-900 hover:bg-white disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-500 disabled:hover:bg-zinc-700"
            >
              {loading ? 'Buscando…' : 'Buscar'}
            </button>
          </div>
        </form>

        {error && <p className="mb-4 rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">{error}</p>}

        {ask && 'ia_activa' in ask && ask.ia_activa === false && (
          <div className="mb-6 flex items-start gap-3 rounded-lg border border-amber-700/60 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
            <span className="shrink-0 rounded-full bg-amber-500/20 px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-300">
              IA desactivada
            </span>
            <span>
              El proyecto no está usando IA ({ask.error}). Te muestro los resultados de la búsqueda
              directa sobre los topics; pueden no ser 100% exactos. Configura <code className="rounded bg-amber-900/40 px-1">KNW_DEEPSEEK_API_KEY</code> para respuestas curadas.
            </span>
          </div>
        )}

        {ask && 'error' in ask && !('ia_activa' in ask) && (
          <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-300">
            La IA no respondió: {ask.error}
          </div>
        )}

        {ask && 'answer' in ask && ask.answer && (
          <section className="mb-8">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-medium text-zinc-400">Respuesta</h2>
              {ask.cached && <span className="text-xs text-zinc-500">(cacheada)</span>}
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 text-sm leading-relaxed text-zinc-200 [&_a]:text-sky-400 [&_a]:underline [&_h1]:text-base [&_h1]:font-semibold [&_h2]:text-base [&_h2]:font-semibold [&_li]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:list-decimal [&_ol]:pl-5">
              <ReactMarkdown>{ask.answer}</ReactMarkdown>
            </div>
          </section>
        )}

        {ask && 'ia_activa' in ask && ask.ia_activa === false && ask.topics && ask.topics.length > 0 && (
          <TopicCards topics={ask.topics} />
        )}

        {((ask && !('ia_activa' in ask)) || !ask) && search && (
          <section>
            <h2 className="mb-3 text-sm font-medium text-zinc-400">
              {search.count} topic{search.count === 1 ? '' : 's'} encontrados
            </h2>
            <TopicCards topics={search.results} />
          </section>
        )}

        {ask && 'ia_activa' in ask && ask.ia_activa === false && (!ask.topics || ask.topics.length === 0) && (
          <p className="text-sm text-zinc-500">Sin resultados para tu búsqueda.</p>
        )}
      </div>

      <LoginModal open={!ready && !checking} onAuthed={() => setReady(true)} />

      {ready && syncStatus && (syncStatus.state === 'importing' || syncStatus.state === 'reindexing') && (
        <div className="fixed top-0 left-0 right-0 z-40 flex items-center justify-center gap-2 bg-sky-950/90 px-4 py-2 text-sm text-sky-200 backdrop-blur-sm">
          <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-sky-400"></span>
          {syncStatus.detail}
        </div>
      )}
    </main>
  )
}

function TopicCards({ topics }: { topics: TopicResult[] }) {
  return (
    <ul className="space-y-4">
      {topics.map(t => (
        <li key={t.folder} className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4">
          <div className="mb-2 flex items-baseline justify-between gap-2">
            <h3 className="font-medium text-zinc-100">{t.topic_title}</h3>
            <span className="truncate font-mono text-xs text-zinc-500">{t.folder}</span>
          </div>
          <ul className="space-y-2">
            {t.hits.map(h => (
              <li key={h.msg_id} className="rounded-lg bg-zinc-800/50 px-3 py-2 text-sm text-zinc-300">
                <span>{h.text}</span>
                {h.links && h.links.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {h.links.map((l, i) => (
                      <li key={i}>
                        <a href={l} target="_blank" rel="noreferrer" className="break-all text-sky-400 underline">
                          {l}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

function LoginModal({ open, onAuthed }: { open: boolean; onAuthed: () => void }) {
  const [step, setStep] = useState<'phone' | 'code' | 'password'>('phone')
  const [phone, setPhone] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  if (!open) return null

  async function handleStart(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/auth/start', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ phone: phone.trim() }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setStep('code')
    } catch (err) {
      setError(`No se pudo enviar el código: ${err}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleComplete(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const body: Record<string, string> = { code: code.trim() }
      if (password) body.password = password.trim()
      const res = await fetch('/api/auth/complete', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data.ok) {
        onAuthed()
      } else if (data.need_password) {
        setStep('password')
      } else {
        setError('Código incorrecto. Intentá de nuevo.')
        setCode('')
      }
    } catch (err) {
      setError(`Error al autenticar: ${err}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-sm rounded-2xl border border-zinc-800 bg-zinc-900 p-6 shadow-2xl">
        <h2 className="mb-1 text-lg font-semibold">Autenticación de Telegram</h2>
        <p className="mb-5 text-sm text-zinc-400">
          Ingresá tu número para conectarte a tu grupo de Telegram.
        </p>

        {step === 'phone' && (
          <form onSubmit={handleStart} className="space-y-3">
            <input
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="+54 11 1234 5678"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-3 text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || !phone.trim()}
              className="w-full rounded-lg bg-zinc-100 px-4 py-3 font-medium text-zinc-900 hover:bg-white disabled:opacity-50"
            >
              {loading ? 'Enviando…' : 'Enviar código'}
            </button>
          </form>
        )}

        {step === 'code' && (
          <form onSubmit={handleComplete} className="space-y-3">
            <p className="text-xs text-zinc-500">
              Se envió un código a <span className="text-zinc-300">{phone}</span>.
            </p>
            <input
              value={code}
              onChange={e => setCode(e.target.value)}
              placeholder="Código de verificación"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-3 text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || !code.trim()}
              className="w-full rounded-lg bg-zinc-100 px-4 py-3 font-medium text-zinc-900 hover:bg-white disabled:opacity-50"
            >
              {loading ? 'Verificando…' : 'Verificar'}
            </button>
          </form>
        )}

        {step === 'password' && (
          <form onSubmit={handleComplete} className="space-y-3">
            <p className="text-xs text-zinc-500">
              Tu cuenta tiene verificación en dos pasos (2FA).
            </p>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Contraseña 2FA"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 px-4 py-3 text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || !password.trim()}
              className="w-full rounded-lg bg-zinc-100 px-4 py-3 font-medium text-zinc-900 hover:bg-white disabled:opacity-50"
            >
              {loading ? 'Verificando…' : 'Verificar'}
            </button>
          </form>
        )}

        {error && (
          <p className="mt-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-sm text-red-300">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
