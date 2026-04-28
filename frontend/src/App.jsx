import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import Navbar from './components/Navbar';
import MainPage from './pages/MainPage';
import UploadAnalysis from './pages/UploadAnalysis';
import StudentMode from './pages/StudentMode';
import TeacherMode from './pages/TeacherMode';
import SessionReport from './pages/SessionReport';
import MyArchive from './pages/MyArchive';
import Register from './pages/Register';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
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
              <Route path="/register" element={<Register />} />
            </Routes>
          </main>
        </div>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
