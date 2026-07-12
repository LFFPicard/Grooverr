import { AddButton } from './AddButton'
import { SourceTag } from './SourceTag'

export function ArtistResultCard({ artist }) {
  return (
    <div className="flex items-center gap-4 bg-panel border border-border rounded-card px-5 py-4 shadow-card dark:shadow-card-dark">
      <div className="w-12 h-12 rounded-full bg-gradient-to-br from-plum-tint to-mustard-tint flex-shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-display text-[0.95rem] font-semibold truncate">{artist.name}</div>
      </div>
      <SourceTag source={artist.source} />
      <AddButton payload={{ type: 'artist', artist }} />
    </div>
  )
}
