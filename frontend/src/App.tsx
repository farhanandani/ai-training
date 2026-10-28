// import { useRoutes } from "react-router-dom";
import { Link, useLocation, useRoutes } from "react-router-dom";
import { useAppContext } from "./api/hooks";
import { Header } from "./components/Header";
import { routes } from "./routes";

export default function App() {
  const page = useRoutes(routes);
  const { data: ctx } = useAppContext();
  const { pathname } = useLocation();
  // F5: no daily log loaded -> the read pages have nothing to show (and must not poll); the Data page still works
  const noData = !!ctx && !ctx.as_of_max && pathname !== "/data";
  return (
    <div className="min-h-screen">
      <Header />
      {/* <main className="mx-auto max-w-7xl px-4 py-6">{page}</main> */}
      <main className="mx-auto max-w-7xl px-4 py-6">
        {noData ? (
          <div role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            No data loaded: there is no daily log to forecast from.{" "}
            <Link to="/data" className="font-medium underline">
              Upload a daily log or reset to the dummy data
            </Link>
            .
          </div>
        ) : (
          page
        )}
      </main>
    </div>
  );
}
