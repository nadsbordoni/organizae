class DocumentExtractionError(Exception):
    code = "document_invalid"
    public_message = "O arquivo está vazio, corrompido ou não pode ser interpretado."


class DocumentTooLargeError(DocumentExtractionError):
    code = "document_too_large"
    public_message = "O documento deve ter no máximo 5 MB."


class UnsupportedDocumentError(DocumentExtractionError):
    code = "document_unsupported"
    public_message = "Envie um arquivo JPG, JPEG, PNG ou PDF válido."


class DocumentComplexityError(DocumentExtractionError):
    code = "document_too_complex"
    public_message = "Envie uma imagem de até 20 milhões de pixels ou um PDF não criptografado de até 20 páginas."


class DocumentDatabaseError(DocumentExtractionError):
    code = "document_database_unavailable"
    public_message = (
        "Não foi possível consultar o contexto financeiro. Tente novamente mais tarde."
    )
