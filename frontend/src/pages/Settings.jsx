import { useEffect, useRef, useState } from 'react'
import {
  useCookieStatus,
  useDeleteCookies,
  usePathPreview,
  useSettings,
  useUpdateSettings,
  useUploadCookies,
  useVersion,
} from '../api/hooks'
import { useTheme } from '../hooks/useTheme'

const QUALITY_OPTIONS = [
  { value: '', label: 'Best available' },
  { value: '128', label: '128 kbps' },
  { value: '192', label: '192 kbps' },
  { value: '256', label: '256 kbps' },
  { value: '320', label: '320 kbps' },
]
const FORMAT_OPTIONS = ['mp3', 'flac', 'm4a', 'opus', 'wav', 'ogg']

function useDebouncedValue(value, delay = 350) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

function Section({ title, description, children }) {
  return (
    <div className="bg-panel border border-border rounded-card shadow-card dark:shadow-card-dark px-6 py-5 mb-5">
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {description && <p className="text-[0.82rem] text-text-dim mt-1 mb-4">{description}</p>}
      <div className={description ? '' : 'mt-4'}>{children}</div>
    </div>
  )
}

const inputClass =
  'bg-panel-sunken border border-border rounded-full px-4 py-2 text-[0.85rem] text-text placeholder:text-text-faint outline-none w-full'
const labelClass = 'block text-[0.78rem] font-semibold text-text-dim mb-1.5'

function CookieUpload() {
  const status = useCookieStatus()
  const upload = useUploadCookies()
  const remove = useDeleteCookies()
  const [dragOver, setDragOver] = useState(false)
  const [localError, setLocalError] = useState(null)
  const inputRef = useRef(null)

  function handleFiles(files) {
    const file = files?.[0]
    if (!file) return
    setLocalError(null)
    upload.mutate(file, {
      onError: (err) => setLocalError(err.message),
    })
  }

  return (
    <div>
      <label
        htmlFor="cookie-file-input"
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragOver(false)
          handleFiles(event.dataTransfer.files)
        }}
        className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-card px-6 py-8 cursor-pointer transition-colors ${
          dragOver ? 'border-plum bg-plum-tint' : 'border-border bg-panel-sunken'
        }`}
      >
        <input
          ref={inputRef}
          id="cookie-file-input"
          type="file"
          accept=".txt"
          className="hidden"
          onChange={(event) => handleFiles(event.target.files)}
        />
        <span className="text-2xl" aria-hidden="true">🍪</span>
        <span className="text-[0.85rem] text-text-dim text-center">
          {upload.isPending
            ? 'Uploading…'
            : 'Drag a cookies.txt file here, or click to browse'}
        </span>
        <span className="text-[0.72rem] text-text-faint">
          Netscape format — export with a "Get cookies.txt" browser extension while logged into YouTube
        </span>
      </label>

      {localError && <div className="text-[0.8rem] text-danger mt-2">{localError}</div>}

      <div className="flex items-center justify-between mt-3">
        {status.isLoading ? (
          <span className="text-[0.8rem] text-text-faint">Checking…</span>
        ) : status.data?.configured ? (
          <span className="text-[0.8rem] text-sage font-medium">
            ✓ Cookies configured
            {status.data.uploaded_at && ` · uploaded ${new Date(status.data.uploaded_at).toLocaleString()}`}
          </span>
        ) : (
          <span className="text-[0.8rem] text-text-faint">No cookies uploaded — optional, only needed for age-restricted content</span>
        )}
        {status.data?.configured && (
          <button
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            className="btn bg-panel-sunken border border-border text-text text-[0.75rem] px-3 py-1.5"
          >
            {remove.isPending ? 'Removing…' : 'Remove'}
          </button>
        )}
      </div>
    </div>
  )
}

function PathTemplateEditor({ value, onChange }) {
  const debounced = useDebouncedValue(value, 350)
  const preview = usePathPreview(debounced)

  return (
    <div>
      <label className={labelClass} htmlFor="path-template">Output path template</label>
      <input
        id="path-template"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="{MusicRoot}/{AlbumArtist}/{Album} ({ReleaseYear})/{DiscNumber-}{TrackNumber} - {Title}.{ext}"
        className={`${inputClass} font-mono text-[0.8rem]`}
      />
      <div className="mt-3 bg-panel-sunken border border-border rounded-lg px-4 py-3">
        <div className="text-[0.7rem] uppercase tracking-wide text-text-faint font-semibold mb-2">Live preview</div>
        {preview.isLoading ? (
          <div className="text-[0.78rem] text-text-faint">…</div>
        ) : preview.isError ? (
          <div className="text-[0.78rem] text-danger">{preview.error.message}</div>
        ) : (
          <div className="flex flex-col gap-1.5 font-mono text-[0.76rem] text-text-dim">
            <div>{preview.data.single_disc_example}</div>
            <div>{preview.data.multi_disc_example} <span className="text-text-faint">(multi-disc)</span></div>
          </div>
        )}
      </div>
    </div>
  )
}

function VersionFooter() {
  const { data } = useVersion()
  if (!data) return null
  const shortSha = data.git_sha.slice(0, 7)
  const buildDate = data.build_date ? new Date(data.build_date).toLocaleString() : null
  return (
    <div className="text-[0.72rem] text-text-faint text-center mt-6 mb-2">
      Grooverr · build {shortSha}
      {buildDate && ` · ${buildDate}`}
    </div>
  )
}

export default function Settings() {
  const settings = useSettings()
  const updateSettings = useUpdateSettings()
  const [theme, toggleTheme] = useTheme()
  const [form, setForm] = useState(null)
  const [saveResult, setSaveResult] = useState(null)

  useEffect(() => {
    if (settings.data && !form) {
      setForm({
        musicbrainz_user_agent: settings.data.musicbrainz_user_agent || '',
        default_quality_ceiling: settings.data.default_quality_ceiling?.toString() || '',
        default_output_format: settings.data.default_output_format,
        output_path_template: settings.data.output_path_template || '',
        playlist_output_folder: settings.data.playlist_output_folder || '',
      })
    }
  }, [settings.data, form])

  if (settings.isLoading || !form) {
    return <div className="text-center text-text-faint text-[0.9rem] py-16">Loading…</div>
  }
  if (settings.isError) {
    return <div className="text-center text-danger text-[0.9rem] py-16">Could not load settings.</div>
  }

  function update(field, value) {
    setForm((f) => ({ ...f, [field]: value }))
    setSaveResult(null)
  }

  function handleSave(event) {
    event.preventDefault()
    updateSettings.mutate(
      {
        musicbrainz_user_agent: form.musicbrainz_user_agent.trim() || null,
        default_quality_ceiling: form.default_quality_ceiling ? Number(form.default_quality_ceiling) : null,
        default_output_format: form.default_output_format,
        output_path_template: form.output_path_template.trim() || null,
        playlist_output_folder: form.playlist_output_folder.trim() || null,
      },
      {
        onSuccess: () => setSaveResult({ ok: true }),
        onError: (err) => setSaveResult({ ok: false, message: err.message }),
      }
    )
  }

  return (
    <form onSubmit={handleSave} className="max-w-2xl">
      <Section title="MusicBrainz" description="No API key needed — MusicBrainz rate-limits by user-agent string instead.">
        <label className={labelClass} htmlFor="mb-ua">User-agent</label>
        <input
          id="mb-ua"
          value={form.musicbrainz_user_agent}
          onChange={(event) => update('musicbrainz_user_agent', event.target.value)}
          placeholder="Grooverr/0.1.0 ( https://github.com/LFFPicard/Grooverr )"
          className={inputClass}
        />
        <p className="text-[0.74rem] text-text-faint mt-1.5">
          Identifies this application to MusicBrainz — not a personal nickname. Almost nobody
          needs to change this from the default; only customize it if you're running a modified
          fork or want a distinct contact string for this deployment.
        </p>
      </Section>

      <Section title="YouTube cookies" description="Optional — only needed to download age-restricted or region-locked videos.">
        <CookieUpload />
      </Section>

      <Section title="Downloads">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass} htmlFor="quality">Default quality ceiling</label>
            <select
              id="quality"
              value={form.default_quality_ceiling}
              onChange={(event) => update('default_quality_ceiling', event.target.value)}
              className={inputClass}
            >
              {QUALITY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="format">Default output format</label>
            <select
              id="format"
              value={form.default_output_format}
              onChange={(event) => update('default_output_format', event.target.value)}
              className={inputClass}
            >
              {FORMAT_OPTIONS.map((f) => (
                <option key={f} value={f}>{f.toUpperCase()}</option>
              ))}
            </select>
          </div>
        </div>
      </Section>

      <Section title="File organization" description="Section 6 naming convention — edit with care, this changes where new downloads land.">
        <div className="mb-5">
          <PathTemplateEditor
            value={form.output_path_template}
            onChange={(value) => update('output_path_template', value)}
          />
        </div>
        <label className={labelClass} htmlFor="playlist-folder">Playlist output folder</label>
        <input
          id="playlist-folder"
          value={form.playlist_output_folder}
          onChange={(event) => update('playlist_output_folder', event.target.value)}
          placeholder="Playlists"
          className={inputClass}
        />
        <p className="text-[0.74rem] text-text-faint mt-1.5">
          Relative to your music root. Playlists are generated .m3u8 files referencing your existing
          library — no audio is ever duplicated. Changing this moves existing playlist files here.
        </p>
      </Section>

      <Section title="Appearance">
        <div className="flex items-center justify-between">
          <span className="text-[0.85rem] text-text">Theme</span>
          <button
            type="button"
            onClick={toggleTheme}
            className="btn bg-panel-sunken border border-border text-text flex items-center gap-2"
          >
            <span aria-hidden="true">◐</span> {theme === 'light' ? 'Light' : 'Dark'}
          </button>
        </div>
      </Section>

      <div className="flex items-center gap-3 sticky bottom-6">
        <button
          type="submit"
          disabled={updateSettings.isPending}
          className="btn btn-plum"
        >
          {updateSettings.isPending ? 'Saving…' : 'Save Settings'}
        </button>
        {saveResult?.ok && <span className="text-[0.82rem] text-sage font-medium">✓ Saved</span>}
        {saveResult && !saveResult.ok && (
          <span className="text-[0.82rem] text-danger">{saveResult.message}</span>
        )}
      </div>

      <VersionFooter />
    </form>
  )
}
