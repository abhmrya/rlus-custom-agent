
(() => {
  "use strict";

  const fileInput = document.querySelector("#document-input");
  const uploadButton = document.querySelector("#document-upload-button");
  const status = document.querySelector("#document-upload-status");
  const locationPanel = document.querySelector("#document-location-panel");
  const locationSelect = document.querySelector("#document-location-select");
  const composer = document.querySelector("#composer");
  const promptInput = document.querySelector("#prompt-input");

  if (
    !fileInput ||
    !uploadButton ||
    !status ||
    !locationPanel ||
    !locationSelect ||
    !composer ||
    !promptInput
  ) {
    console.error("Document upload: required UI elements not found.");
    return;
  }

  const MAX_FILE_SIZE = 15 * 1024 * 1024;
  const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".txt"];
  const SESSION_STORAGE_KEY = "databricks-agentbricks-session-id";

  let uploadedDocument = null;
  let uploading = false;

  function setStatus(message) {
    status.textContent = message;
  }

  function clearDocument() {
    uploadedDocument = null;
    fileInput.value = "";

    locationSelect.innerHTML =
      '<option value="">Select a location</option>';

    locationPanel.hidden = true;
    setStatus("PDF, DOCX or TXT");
  }

  function getDocumentText(result) {
    return (
      result.document_text ||
      result.extracted_text ||
      result.text ||
      result.content ||
      ""
    );
  }

  function getLocations(result) {
    const locations =
      result.locations ||
      result.detected_locations ||
      [];

    if (!Array.isArray(locations)) {
      return [];
    }

    return [
      ...new Set(
        locations
          .map((item) => {
            if (typeof item === "string") {
              return item.trim();
            }

            return (
              item?.name ||
              item?.location ||
              ""
            ).trim();
          })
          .filter(Boolean)
      )
    ];
  }

  function renderLocations(locations) {
    locationSelect.innerHTML =
      '<option value="">Select a location</option>';

    locations.forEach((location) => {
      const option = document.createElement("option");

      option.value = location;
      option.textContent = location;

      locationSelect.appendChild(option);
    });

    if (locations.length === 1) {
      locationSelect.value = locations[0];
    }

    locationPanel.hidden = locations.length === 0;
  }

  async function uploadDocument(file) {
    if (uploading) return;

    const extension =
      "." + file.name.split(".").pop().toLowerCase();

    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      setStatus("Unsupported file. Use PDF, DOCX or TXT.");
      return;
    }

    if (file.size > MAX_FILE_SIZE) {
      setStatus("File is too large. Maximum size is 15 MB.");
      return;
    }

    uploading = true;
    uploadButton.disabled = true;

    setStatus("Uploading and extracting document...");

    try {
      const sessionId = localStorage.getItem(
        SESSION_STORAGE_KEY
      );

      if (!sessionId) {
        throw new Error(
          "Session ID is not initialized. Refresh the Workbench and try again."
        );
      }

      const formData = new FormData();
      formData.append("file", file);

      const uploadUrl = new URL(
        "/api/demo/documents/upload",
        window.location.origin
      );

      uploadUrl.searchParams.set(
        "session_id",
        sessionId
      );

      const response = await fetch(uploadUrl.toString(), {
        method: "POST",
        body: formData
      });

      const result = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(
          result.detail ||
          result.message ||
          `Upload failed: HTTP ${response.status}`
        );
      }

      const extractedText = getDocumentText(result);

      if (!extractedText.trim()) {
        throw new Error(
          "Upload succeeded, but extracted text was not returned."
        );
      }

      const locations = getLocations(result);

      uploadedDocument = {
        filename: file.name,
        text: extractedText,
        locations,
        documentId: result.document_id || result.id || null
      };

      renderLocations(locations);

      setStatus(
        `Uploaded: ${file.name} | ` +
        `${extractedText.length} characters | ` +
        `${locations.length} location(s) found`
      );

      console.log("Document upload result:", {
        filename: file.name,
        characters: extractedText.length,
        locations,
        persisted: result.persisted
      });

    } catch (error) {
      console.error("Document upload error:", error);
      clearDocument();
      setStatus(error.message || "Document upload failed.");

    } finally {
      uploading = false;
      uploadButton.disabled = false;
    }
  }

  uploadButton.addEventListener("click", () => {
    fileInput.click();
  });

  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];

    if (file) {
      uploadDocument(file);
    }
  });

  locationSelect.addEventListener("change", () => {
    if (locationSelect.value) {
      setStatus(
        `Selected location: ${locationSelect.value}`
      );
    } else if (uploadedDocument) {
      setStatus(
        `${uploadedDocument.locations.length} location(s) available in document.`
      );
    }
  });

  // Capture the submit before app.js reads the prompt.
  composer.addEventListener(
    "submit",
    (event) => {
      if (!uploadedDocument) return;

      if (uploading) {
        event.preventDefault();
        event.stopImmediatePropagation();

        setStatus(
          "Please wait until document upload finishes."
        );

        return;
      }

      const selectedLocation = locationSelect.value;
      const detectedLocations = uploadedDocument.locations;

      const originalPrompt = promptInput.value;

      const documentContext = [
        "[UPLOADED DOCUMENT CONTEXT]",

        `Filename: ${uploadedDocument.filename}`,

        uploadedDocument.documentId
          ? `Document ID: ${uploadedDocument.documentId}`
          : "",

        selectedLocation
          ? `Selected location: ${selectedLocation}`
          : "No location selected by the user.",

        `All detected document locations: ${JSON.stringify(detectedLocations)}`,

        detectedLocations.length > 0
          ? "When the user explicitly requests weather for all document locations, use the complete detected locations list above."
          : "No location was detected in this document.",

        "Extracted document text:",

        uploadedDocument.text,

        "[END DOCUMENT CONTEXT]"
      ]
        .filter(Boolean)
        .join("\n");

      // app.js will read this original question for error recovery.
      promptInput.dataset.documentOriginalPrompt = originalPrompt;

      // app.js reads this complete message and clears the composer.
      promptInput.value =
        originalPrompt +
        "\n\n" +
        documentContext;
    },
    true
  );

  // Reset the temporary location after successful processing.
  // Keep the uploaded document available for follow-up questions.
  document.addEventListener("rlus:message-sent", () => {
    if (!uploadedDocument) return;

    locationSelect.value = "";

    setStatus(
      `Document ready: ${uploadedDocument.filename} | ` +
      `${uploadedDocument.locations.length} location(s) found`
    );
  });

  console.log("Document upload feature initialized.");
})();
