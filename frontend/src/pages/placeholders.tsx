import { useParams } from "react-router-dom";

// Placeholders: Tasks 17-19 replace these with the real pages.
function Placeholder({ title }: { title: string }) {
  return (
    <section className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-slate-600">
      <h2 className="text-base font-semibold text-slate-800">{title}</h2>
      <p className="mt-1 text-sm">This screen is built in a later task.</p>
    </section>
  );
}

export const FleetPage = () => <Placeholder title="Fleet Overview" />;
export const AtmDetailPage = () => <Placeholder title={`ATM Detail ${useParams().tid ?? ""}`} />;
export const PlannerPage = () => <Placeholder title="Allocation Planner" />;
export const DataPage = () => <Placeholder title="Data Editor" />;
export const AccuracyPage = () => <Placeholder title="Forecast Accuracy" />;
