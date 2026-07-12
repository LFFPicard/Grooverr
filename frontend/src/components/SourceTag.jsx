export function SourceTag({ source }) {
  return (
    <span className="text-[0.68rem] text-text-faint bg-panel-sunken border border-border px-2 py-0.5 rounded-full flex-shrink-0 whitespace-nowrap">
      {source === 'musicbrainz' ? 'MusicBrainz' : 'YouTube Music'}
    </span>
  )
}
