class BridgeError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        return dict(code=self.code, message=self.message, details=self.details)
