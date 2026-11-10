/** Stand-alone 3D viewer route, kept for deep links; the passport page embeds the same viewer. */
import type { EngineeringFile, FileVersion } from "@passport/api-types";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import ModelViewer from "../components/ModelViewer";
import { ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";

export default function ModelViewerPage() {
  const { id, number } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const file = useApi<EngineeringFile>(`/files/${id}/`);
  const versions = useApi<FileVersion[]>(`/files/${id}/versions/`);
  const version = versions.data?.find((v) => String(v.version_number) === number);
  const revision = params.get("rev") ?? `v${number}`;

  return (
    <>
      <button type="button" className="back-link" onClick={() => navigate(-1)}>
        &larr; Back
      </button>
      <PageHeader title={file.data ? `3D model · ${file.data.title}` : "3D model"} subtitle={`Revision ${revision} · STEP-derived GLB`} />
      <Notice>Viewer derivative generated from the STEP original. Production CAD fidelity on real engineering files has not been verified yet.</Notice>
      <ErrorNotice error={file.error ?? versions.error} />
      {versions.loading && !versions.data ? <Loading /> : version ? <ModelViewer fileId={id!} version={version} revisionLabel={revision} /> : !versions.error && <ErrorNotice error={new Error("This file version was not found.")} />}
    </>
  );
}
