resource "aws_s3_bucket" "tool_payloads" {
  bucket = "stock-research-tool-payloads-${var.env}"
}

resource "aws_s3_bucket_lifecycle_configuration" "expire_old_payloads" {
  bucket = aws_s3_bucket.tool_payloads.id
  rule {
    id     = "expire-after-30-days"
    status = "Enabled"
    filter {}
    expiration {
      days = 30 # payloads are re-fetched well before this per their own TTL; this is a backstop
    }
  }
}

resource "aws_s3_bucket_public_access_block" "block_all" {
  bucket                  = aws_s3_bucket.tool_payloads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
