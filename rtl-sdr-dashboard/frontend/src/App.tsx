import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import Connections from './pages/Connections'
import RadioPlayer from './pages/RadioPlayer'
import Scheduler from './pages/Scheduler'
import { Radio, LayoutDashboard, Plug, CalendarClock } from 'lucide-react'

function NavItem({ to, icon: Icon, label }: { to: string; icon: React.ElementType; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? 'bg-sky-600 text-white'
            : 'text-gray-400 hover:text-white hover:bg-gray-800'
        }`
      }
    >
      <Icon size={18} />
      {label}
    </NavLink>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col">
        <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center gap-6">
          <div className="flex items-center gap-2 mr-4">
            <Radio className="text-sky-400" size={24} />
            <span className="font-bold text-lg tracking-wide">RTL-SDR Dashboard</span>
          </div>
          <nav className="flex gap-2">
            <NavItem to="/" icon={LayoutDashboard} label="Dashboard" />
            <NavItem to="/connections" icon={Plug} label="Connections" />
            <NavItem to="/radio" icon={Radio} label="Radio Player" />
            <NavItem to="/scheduler" icon={CalendarClock} label="Scheduler" />
          </nav>
        </header>
        <main className="flex-1 p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/connections" element={<Connections />} />
            <Route path="/radio" element={<RadioPlayer />} />
            <Route path="/scheduler" element={<Scheduler />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
