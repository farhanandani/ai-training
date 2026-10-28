import { useRoutes } from "react-router-dom";
import { Header } from "./components/Header";
import { routes } from "./routes";

export default function App() {
  const page = useRoutes(routes);
  return (
    <div className="min-h-screen">
      <Header />
      <main className="mx-auto max-w-7xl px-4 py-6">{page}</main>
    </div>
  );
}
