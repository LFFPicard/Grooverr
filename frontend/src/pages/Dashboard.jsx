import { Link } from 'react-router-dom'
import { useActiveQueue, useActivity, useIncompleteAlbums, useStats } from '../api/hooks'
import { StatCard } from '../components/StatCard'
import { Panel } from '../components/Panel'
import { QueueRow } from '../components/QueueRow'
import { ActivityItem } from '../components/ActivityItem'
import { AlbumCard } from '../components/AlbumCard'

function EmptyState({ children }) {
  return <div className="px-5 py-8 text-center text-[0.85rem] text-text-faint">{children}</div>
}

export default function Dashboard() {
  const stats = useStats()
  const activeQueue = useActiveQueue(6)
  const activity = useActivity(6)
  const incompleteAlbums = useIncompleteAlbums(6)

  const s = stats.data

  return (
    <div>
      <div className="grid grid-cols-4 gap-4 mb-9">
        <StatCard
          label="Downloading"
          value={stats.isLoading ? '—' : s.downloading}
          sub={!stats.isLoading && (s.downloading === 0 ? 'idle' : `${s.downloading} active now`)}
          accent="mustard"
        />
        <StatCard
          label="Queued"
          value={stats.isLoading ? '—' : s.queued}
          sub={!stats.isLoading && (s.queued === 0 ? 'nothing waiting' : 'waiting to start')}
          accent="faint"
        />
        <StatCard
          label="Library"
          value={stats.isLoading ? '—' : s.library_tracks}
          sub={!stats.isLoading && `tracks · ${s.library_albums} albums`}
          accent="sage"
        />
        <StatCard
          label="Incomplete albums"
          value={stats.isLoading ? '—' : s.incomplete_albums}
          sub={
            !stats.isLoading &&
            (s.incomplete_albums === 0 ? 'all albums complete' : `${s.library_albums - s.incomplete_albums} complete`)
          }
          accent="danger"
        />
      </div>

      <div className="grid grid-cols-[1.4fr_1fr] gap-5 mb-9">
        <Panel title="Active Queue" tag={!activeQueue.isLoading && `${activeQueue.items.length} shown`}>
          {activeQueue.isLoading ? (
            <EmptyState>Loading…</EmptyState>
          ) : activeQueue.items.length === 0 ? (
            <EmptyState>No downloads queued — search above to add music.</EmptyState>
          ) : (
            activeQueue.items.map((job) => <QueueRow key={job.id} job={job} />)
          )}
        </Panel>

        <Panel title="Recent Activity">
          {activity.isLoading ? (
            <EmptyState>Loading…</EmptyState>
          ) : activity.data.items.length === 0 ? (
            <EmptyState>Nothing here yet — completed and failed jobs will show up here.</EmptyState>
          ) : (
            activity.data.items.map((item) => <ActivityItem key={item.id} item={item} />)
          )}
        </Panel>
      </div>

      <div className="flex items-baseline justify-between mb-4">
        <h2 className="font-display text-xl font-semibold">Library — Incomplete Albums</h2>
        {!stats.isLoading && s.library_albums > 0 && (
          <Link to="/library" className="text-[0.78rem] text-plum font-medium hover:underline">
            View all →
          </Link>
        )}
      </div>

      {stats.isLoading || incompleteAlbums.isLoading ? (
        <div className="text-[0.85rem] text-text-faint">Loading…</div>
      ) : s.library_albums === 0 ? (
        <div className="bg-panel border border-border rounded-card px-6 py-10 text-center text-[0.85rem] text-text-faint">
          No albums yet — search above to start building your library.
        </div>
      ) : incompleteAlbums.data.items.length === 0 ? (
        <div className="bg-panel border border-border rounded-card px-6 py-10 text-center text-[0.85rem] text-text-dim">
          Every album in your library is complete.
        </div>
      ) : (
        <div className="grid grid-cols-5 gap-[18px]">
          {incompleteAlbums.data.items.map((album) => (
            <AlbumCard key={album.id} album={album} />
          ))}
        </div>
      )}
    </div>
  )
}
