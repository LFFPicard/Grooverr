import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { useQueueEvents } from './hooks/useQueueEvents'
import Dashboard from './pages/Dashboard'
import Search from './pages/Search'
import Library from './pages/Library'
import AlbumDetail from './pages/AlbumDetail'
import Queue from './pages/Queue'
import Settings from './pages/Settings'

export default function App() {
  useQueueEvents()

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/search" element={<Search />} />
        <Route path="/library" element={<Library />} />
        <Route path="/library/album/:albumId" element={<AlbumDetail />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  )
}
