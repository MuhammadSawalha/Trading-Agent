output "table_arns" {
  value = [aws_dynamodb_table.tool_results.arn, aws_dynamodb_table.agent_outputs.arn, aws_dynamodb_table.process_history.arn]
}

output "tool_results_table_name" {
  value = aws_dynamodb_table.tool_results.name
}

output "agent_outputs_table_name" {
  value = aws_dynamodb_table.agent_outputs.name
}

output "process_history_table_name" {
  value = aws_dynamodb_table.process_history.name
}
