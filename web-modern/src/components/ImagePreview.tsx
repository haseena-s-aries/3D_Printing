/** Full-size photograph through a single-use, audited preview link (shared by Documents and Quick view). */
import type { EngineeringFile } from "@passport/api-types";
import { useEffect, useState } from "react";

import { api, sameOriginUrl } from "../api/client";
import { ErrorNotice, Loading } from "./ui";

export default function ImagePreview({ file, version }: { file: Pick<EngineeringFile, "id" | "title">; version: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let cancelled = false;
    api<{ url: string }>(`/files/${file.id}/versions/${version}/download-link/`, { body: { variant: "preview" } })
      .then((l) => !cancelled && setUrl(sameOriginUrl(l.url)))
      .catch((e: unknown) => !cancelled && setError(e));
    return () => {
      cancelled = true;
    };
  }, [file.id, version]);
  if (error) return <ErrorNotice error={error} />;
  return url ? <img className="photo-preview" src={url} alt={`${file.title}, version ${version}`} /> : <Loading />;
}
