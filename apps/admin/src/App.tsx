import { BrowserRouter, Route, Routes } from "react-router-dom";

import LoginRoute from "@/routes/login";
import NotFoundRoute from "@/routes/not-found";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LoginRoute />} />
        <Route path="*" element={<NotFoundRoute />} />
      </Routes>
    </BrowserRouter>
  );
}
