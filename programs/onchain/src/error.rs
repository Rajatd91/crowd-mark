use anchor_lang::prelude::*;

#[error_code]
pub enum ErrorCode {
    #[msg("Only the feed authority may do this")]
    Unauthorized,
    #[msg("Only the configured publisher may publish a mark")]
    NotPublisher,
    #[msg("A probability must be between 0 and 10000 basis points")]
    ProbabilityOutOfRange,
    #[msg("A published value must be greater than zero")]
    ValueNotPositive,
    #[msg("The low end of the range cannot exceed the high end")]
    RangeInverted,
    #[msg("The published value must sit inside its own stated range")]
    ValueOutsideRange,
    #[msg("The reading claims to come from the future")]
    ReadingFromTheFuture,
    #[msg("The reading is too old to publish; read the markets again")]
    ReadingTooOld,
    #[msg("A mark may not be replaced by an older reading")]
    NotNewerThanStored,
    #[msg("Symbol must be 1 to 12 characters, A to Z only")]
    InvalidSymbol,
    #[msg("Company name must be 1 to 24 characters")]
    InvalidCompany,
    #[msg("Kind must be 0 for a listing or 1 for a private valuation")]
    InvalidKind,
}
