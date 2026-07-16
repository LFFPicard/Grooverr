import { useState } from 'react'
import { useCancelJob, useClearJobs, useQueueTab, useRetryJob } from '../api/hooks'
import { QueueRow } from '../components/QueueRow'

const TABS = [
  { key: 'metadata_resolve', label: 'Resolving' },
  { key: 'download', label: 'Downloading' },
]
const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'queued', label: 'Queued' },
  { value: 'done', label: 'Done' },
  { value: 'error', label: 'Error' },
]
const PAGE_SIZE = 20

function JobActions({ job }) {
  const retry = useRetryJob()
  const cancel = useCancelJob()

  if (job.status === 'error') {
    return (
      <button
        onClick={() => retry.mutate(job.id)}
        disabled={retry.isPending}
        className="btn bg-panel-sunken border border-border text-text text-[0.75rem] px-3 py-1.5"
      >
        {retry.isPending ? '…' : 'Retry'}
      </button>
    )
  }
  if (job.status === 'queued') {
    return (
      <button
        onClick={() => cancel.mutate(job.id)}
        disabled={cancel.isPending}
        className="btn bg-panel-sunken border border-border text-text text-[0.75rem] px-3 py-1.5"
      >
        {cancel.isPending ? '…' : 'Cancel'}
      </button>
    )
  }
  return null
}

function ClearButtons() {
  const clear = useClearJobs()
  const [lastCleared, setLastCleared] = useState(null)

  function handleClear(status) {
    setLastCleared(null)
    clear.mutate(status, {
      onSuccess: (data) => setLastCleared(`${data.cleared} ${data.status} job${data.cleared === 1 ? '' : 's'} cleared`),
    })
  }

  return (
    <div className="flex items-center gap-2">
      {lastCleared && <span className="text-[0.78rem] text-text-faint">{lastCleared}</span>}
      <button
        onClick={() => handleClear('error')}
        disabled={clear.isPending}
        className="btn bg-panel-sunken border border-border text-text text-[0.78rem] px-3 py-1.5 disabled:opacity-50"
      >
        Clear failed
      </button>
      <button
        onClick={() => handleClear('done')}
        disabled={clear.isPending}
        className="btn bg-panel-sunken border border-border text-text text-[0.78rem] px-3 py-1.5 disabled:opacity-50"
      >
        Clear completed
      </button>
    </div>
  )
}

export default function Queue() {
  const [tab, setTab] = useState('metadata_resolve')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(0)

  const { data, isLoading, isError } = useQueueTab(tab, status || undefined, page)

  function switchTab(nextTab) {
    setTab(nextTab)
    setPage(0)
  }
  function switchStatus(nextStatus) {
    setStatus(nextStatus)
    setPage(0)
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div>
      <div className="flex items-center gap-2 mb-6">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => switchTab(t.key)}
            className={`text-[0.85rem] font-medium px-4 py-2 rounded-full transition-colors ${
              tab === t.key ? 'text-plum bg-plum-tint font-semibold' : 'text-text-dim bg-panel-sunken border border-border hover:text-text'
            }`}
          >
            {t.label}
          </button>
        ))}
        <select
          value={status}
          onChange={(event) => switchStatus(event.target.value)}
          className="ml-auto bg-panel-sunken border border-border rounded-full px-3.5 py-2 text-[0.82rem] text-text outline-none"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ClearButtons />
      </div>

      <div className="bg-panel border border-border rounded-card overflow-hidden shadow-card dark:shadow-card-dark">
        {isLoading ? (
          <div className="px-5 py-10 text-center text-text-faint text-[0.85rem]">Loading…</div>
        ) : isError ? (
          <div className="px-5 py-10 text-center text-danger text-[0.85rem]">Could not load the queue.</div>
        ) : data.items.length === 0 ? (
          <div className="px-5 py-10 text-center text-text-faint text-[0.85rem]">
            Nothing here — {tab === 'metadata_resolve' ? 'no metadata resolution jobs' : 'no downloads'}
            {status && ` with status "${status}"`}.
          </div>
        ) : (
          data.items.map((job) => <QueueRow key={job.id} job={job} actions={<JobActions job={job} />} />)
        )}
      </div>

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between mt-4 text-[0.82rem] text-text-dim">
          <span>
            Page {page + 1} of {totalPages} · {data.total} total
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="btn bg-panel-sunken border border-border text-text px-3 py-1.5 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="btn bg-panel-sunken border border-border text-text px-3 py-1.5 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
