import { ArrowLeft } from "lucide-react";
import { LinkButton, PageBand } from "../components/ui";

export default function NotFound() {
  return (
    <>
      <PageBand />
      <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-32 text-center">
        <p className="text-sm text-teal">error: target not found</p>
        <h1 className="mt-3 text-4xl font-semibold text-violet">There is no page here.</h1>
        <p className="mt-4 text-muted">It may have moved, or the link was mistyped.</p>
        <div className="mt-8 flex gap-3">
          <LinkButton to="/"><ArrowLeft size={17} /> Home</LinkButton>
          <LinkButton to="/docs" kind="outline">Documentation</LinkButton>
        </div>
      </div>
    </>
  );
}
