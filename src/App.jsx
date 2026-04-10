import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import MainPage from './pages/MainPage';
import UploadAnalysis from './pages/UploadAnalysis';
import StudentMode from './pages/StudentMode';
import TeacherMode from './pages/TeacherMode';
import SessionReport from './pages/SessionReport';
import MyArchive from './pages/MyArchive';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <div className="app-layout">
        <Navbar />
        <main className="page-content">
          <Routes>
            <Route path="/" element={<MainPage />} />
            <Route path="/upload" element={<UploadAnalysis />} />
            <Route path="/student" element={<StudentMode />} />
            <Route path="/teacher" element={<TeacherMode />} />
            <Route path="/report" element={<SessionReport />} />
            <Route path="/archive" element={<MyArchive />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
