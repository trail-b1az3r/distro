import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router";
import { prettyName } from "./brand";
import { Footer } from "./components/ui";
import Home from "./pages/Home";
import NotFound from "./pages/NotFound";

// The documentation (every page's Markdown and the renderer) loads when first opened.
const Docs = lazy(() => import("./pages/Docs"));

/** A new page starts at its top, or at the #section its link names. */
function Scroll() {
  const { pathname, hash } = useLocation();
  useEffect(() => {
    if (pathname === "/") document.title = prettyName;
    if (!hash) {
      window.scrollTo(0, 0);
      return;
    }
    // The target may not be rendered yet (another page, or the docs loading).
    const id = decodeURIComponent(hash.slice(1));
    let tries = 0;
    let timer;
    const seek = () => {
      const el = document.getElementById(id);
      if (el) el.scrollIntoView();
      else if (tries++ < 40) timer = setTimeout(seek, 50);
    };
    seek();
    return () => clearTimeout(timer);
  }, [pathname, hash]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL}>
      <Scroll />
      <div className="flex min-h-screen flex-col">
        <div className="flex-1">
          <Suspense fallback={<div className="min-h-[60vh]" />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/docs" element={<Docs />} />
              <Route path="/docs/:slug" element={<Docs />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </div>
        <Footer />
      </div>
    </BrowserRouter>
  );
}
