import { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import Icon from "./Icon";

export default function CsvDropzone({ onFileSelected, disabled }) {
  const [rejection, setRejection] = useState(null);

  const onDrop = useCallback(
    (acceptedFiles, fileRejections) => {
      setRejection(null);
      if (fileRejections.length > 0) {
        setRejection("Only .csv files are accepted.");
        return;
      }
      if (acceptedFiles.length > 0) {
        onFileSelected(acceptedFiles[0]);
      }
    },
    [onFileSelected]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    disabled,
    multiple: false,
    accept: { "text/csv": [".csv"] },
  });

  return (
    <div>
      <div {...getRootProps()} className={"dropzone" + (isDragActive ? " active" : "")}>
        <input {...getInputProps()} />
        <Icon name="upload_file" size={40} className="dropzone-icon" />
        <div className="dropzone-title">
          {isDragActive ? "Drop the CSV to begin analysis" : "Drag & drop an observational CSV here"}
        </div>
        <div className="dropzone-subtitle">or click to browse — .csv files only</div>
      </div>
      {rejection && (
        <p role="alert" style={{ color: "var(--danger)", fontSize: "0.85rem", marginTop: 10 }}>
          {rejection}
        </p>
      )}
    </div>
  );
}
