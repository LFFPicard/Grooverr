function describe(item) {
  const title = item.track_title || 'a track'
  const titleEl = <span className="text-text font-semibold">{title}</span>

  if (item.job_type === 'download') {
    if (item.status === 'done') {
      const where = [item.artist_name, item.album_title].filter(Boolean).join(' · ')
      return {
        text: (
          <>
            Downloaded {titleEl}
            {where && <> — {where}</>}
          </>
        ),
        error: false,
      }
    }
    return {
      text: (
        <>
          Download failed for {titleEl}: {item.error_message}
        </>
      ),
      error: true,
    }
  }

  if (item.status === 'done') {
    return { text: <>Resolved metadata for {titleEl}</>, error: false }
  }
  return {
    text: (
      <>
        Metadata resolution failed for {titleEl}: {item.error_message}
      </>
    ),
    error: true,
  }
}

export function ActivityItem({ item }) {
  const { text, error } = describe(item)
  return (
    <div className="flex gap-2.5 px-5 py-3 border-b border-border last:border-b-0 text-[0.82rem] text-text-dim">
      <span className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${error ? 'bg-danger' : 'bg-sage'}`} />
      <span>{text}</span>
    </div>
  )
}
