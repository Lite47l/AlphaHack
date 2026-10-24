import { createRoot } from 'react-dom/client';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ClientProvider, FeedProvider } from './lib/context';
import { ComparePage } from './pages/ComparePage';
import { HomePage } from './pages/HomePage';
import { InsightPage } from './pages/InsightPage';
import { MonitoringPage } from './pages/MonitoringPage';
import { NewsPage } from './pages/NewsPage';
import { ProfilePage } from './pages/ProfilePage';
import { NotFoundPage, StubPage } from './pages/StubPage';
import './styles/app.css';

// StrictMode не используется намеренно: двойной вызов эффектов в dev создавал бы лишние POST /insights.
createRoot(document.getElementById('root')!).render(
  <BrowserRouter>
    <ClientProvider>
      <FeedProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="news" element={<NewsPage />} />
            <Route path="news/:newsId" element={<InsightPage />} />
            <Route path="compare" element={<ComparePage />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="monitoring" element={<MonitoringPage />} />
            <Route path="stub/:section" element={<StubPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </FeedProvider>
    </ClientProvider>
  </BrowserRouter>,
);
