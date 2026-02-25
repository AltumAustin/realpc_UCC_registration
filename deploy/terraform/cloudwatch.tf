# --- SNS Topic for Alerts ---

resource "aws_sns_topic" "ucc_alerts" {
  name = "ucc-ingestion-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.ucc_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- CloudWatch Log Group ---

resource "aws_cloudwatch_log_group" "ucc_ingestion" {
  name              = "/ucc-ingestion"
  retention_in_days = 30
}

# --- Metric Filter: detect ingestion failures ---

resource "aws_cloudwatch_log_metric_filter" "ingestion_failures" {
  name           = "ucc-ingestion-failures"
  log_group_name = aws_cloudwatch_log_group.ucc_ingestion.name
  pattern        = "?FAILED ?\"status=failed\" ?\"status\": \"failed\""

  metric_transformation {
    name          = "IngestionFailures"
    namespace     = "UCC/Ingestion"
    value         = "1"
    default_value = "0"
  }
}

# --- CloudWatch Alarm ---

resource "aws_cloudwatch_metric_alarm" "ingestion_failure" {
  alarm_name          = "ucc-ingestion-failure"
  alarm_description   = "Triggers when UCC ingestion run reports failure"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "IngestionFailures"
  namespace           = "UCC/Ingestion"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.ucc_alerts.arn]
  ok_actions    = [aws_sns_topic.ucc_alerts.arn]
}
