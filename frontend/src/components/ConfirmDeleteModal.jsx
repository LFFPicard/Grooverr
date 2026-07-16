import { useEffect } from 'react'

// Section 7.6: the first genuinely irreversible action in the product.
// Two explicit buttons for the delete_files choice — never a checkbox
// someone could tick past without noticing.
export function ConfirmDeleteModal({
  open,
  title,
  description,
  busy = false,
  onCancel,
  onConfirm,
}) {
  useEffect(() => {
    if (!open) return
    function onKeyDown(event) {
      if (event.key === 'Escape' && !busy) onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, busy, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={() => !busy && onCancel()}
    >
      <div
        role="dialog"
        aria-modal="true"
        className="w-full max-w-md bg-panel border border-border rounded-card shadow-card dark:shadow-card-dark p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="font-display text-xl font-semibold">{title}</h2>
        <p className="text-[0.85rem] text-text-dim mt-2 leading-relaxed">{description}</p>

        <div className="flex flex-col gap-2 mt-6">
          <button
            onClick={() => onConfirm(true)}
            disabled={busy}
            className="btn w-full bg-danger text-white disabled:opacity-50"
          >
            {busy ? 'Removing…' : 'Remove and delete files'}
          </button>
          <button
            onClick={() => onConfirm(false)}
            disabled={busy}
            className="btn w-full bg-panel-sunken border border-border text-text disabled:opacity-50"
          >
            {busy ? 'Removing…' : 'Remove from library'}
          </button>
          <button
            onClick={onCancel}
            disabled={busy}
            className="text-[0.8rem] text-text-faint hover:text-text mt-1 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
