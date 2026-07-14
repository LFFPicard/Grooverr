import { Link } from 'react-router-dom'

/**
 * Shared card shell for the Library grid (Albums and Playlists tabs) —
 * same completeness-badge treatment for both, per the Section 8 decision
 * to reuse one component rather than building parallel ones. Albums link
 * to Album Detail; playlists have no detail screen, so they render an
 * inline `action` (Complete this playlist) instead.
 */
export function LibraryCard({ title, subtitle, coverArtUrl, downloadedTracks, expectedTracks, completeness, to, action }) {
  const isComplete = completeness === 'complete'
  const badgeClass = isComplete ? 'bg-sage text-white' : 'bg-mustard text-white'
  const missing = expectedTracks - downloadedTracks
  const Wrapper = to ? Link : 'div'
  const wrapperProps = to ? { to } : {}

  return (
    <div className="bg-panel border border-border rounded-card overflow-hidden shadow-card dark:shadow-card-dark">
      <Wrapper
        {...wrapperProps}
        className={`block ${to ? 'transition-transform hover:-translate-y-0.5' : ''}`}
      >
        <div className="aspect-square bg-gradient-to-br from-plum-tint to-mustard-tint relative">
          {coverArtUrl && (
            <img src={coverArtUrl} alt="" loading="lazy" className="w-full h-full object-cover absolute inset-0" />
          )}
          <span className={`absolute top-2.5 right-2.5 font-mono text-[0.65rem] font-semibold px-2 py-0.5 rounded-full ${badgeClass}`}>
            {downloadedTracks}/{expectedTracks}
          </span>
        </div>
        <div className="px-4 py-3.5">
          <div className="font-display text-[0.95rem] font-semibold truncate">{title}</div>
          <div className="text-[0.78rem] text-text-faint mt-0.5 truncate">{subtitle}</div>
          <div className="text-[0.72rem] text-text-dim mt-2.5">
            {downloadedTracks} of {expectedTracks} tracks
            {missing > 0 && ` · missing ${missing}`}
          </div>
        </div>
      </Wrapper>
      {action && <div className="px-4 pb-4">{action}</div>}
    </div>
  )
}
