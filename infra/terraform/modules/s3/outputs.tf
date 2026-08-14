output "bucket_arn" {
  value = aws_s3_bucket.tool_payloads.arn
}

output "bucket_name" {
  value = aws_s3_bucket.tool_payloads.bucket
}
