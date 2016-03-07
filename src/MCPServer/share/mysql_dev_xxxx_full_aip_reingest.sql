-- Add SIPUUID argument to restructureForCompliance_v0.0
UPDATE `StandardTasksConfigs` SET `arguments` = '"%SIPDirectory%" "%SIPUUID%"' WHERE `execute` = 'restructureForCompliance_v0.0';

-- Add sharedPath argument to updateSizeAndChecksum_v0.0
UPDATE `StandardTasksConfigs` SET `arguments` = '"%sharedPath%" --filePath "%relativeLocation%" --fileUUID "%fileUUID%" --eventIdentifierUUID "%taskUUID%" --date "%date%"' WHERE `execute` = 'updateSizeAndChecksum_v0.0';

-- Add failedTransferCleanup script to failed
INSERT INTO StandardTasksConfigs (pk, requiresOutputLock, execute, arguments) VALUES ('3362ef11-b4f1-4862-b91d-496665d15cce', 0, 'failedTransferCleanup', '"fail" "%SIPUUID%" "%SIPDirectory%"');
INSERT INTO TasksConfigs (pk, taskType, taskTypePKReference, description) VALUES ('6b2a7301-df99-4157-b09f-76e87e08f6d9', '36b2e239-4a57-4aa5-8ebc-7a29139baca6', '3362ef11-b4f1-4862-b91d-496665d15cce', 'Cleanup failed Transfer');
INSERT INTO MicroServiceChainLinks(pk, microserviceGroup, defaultExitMessage, currentTask, defaultNextChainLink) VALUES ('e780473a-0c10-431f-bab6-5d7238b2b70b', 'Failed transfer', 'Failed', '6b2a7301-df99-4157-b09f-76e87e08f6d9', '377f8ebb-7989-4a68-9361-658079ff8138');
INSERT INTO MicroServiceChainLinksExitCodes (pk, microServiceChainLink, exitCode, nextMicroServiceChainLink, exitMessage) VALUES ('f4abbac5-558b-4c2b-8f4f-cdf13cf57249', 'e780473a-0c10-431f-bab6-5d7238b2b70b', 0, '377f8ebb-7989-4a68-9361-658079ff8138', 'Completed successfully');
UPDATE MicroServiceChainLinksExitCodes SET nextMicroServiceChainLink='e780473a-0c10-431f-bab6-5d7238b2b70b' WHERE microServiceChainLink='61c316a6-0a50-4f65-8767-1f44b1eeb6dd';
-- Add failedTransferCleanup script to rejected
INSERT INTO StandardTasksConfigs (pk, requiresOutputLock, execute, arguments) VALUES ('72f11e68-7350-42a7-9bdc-60001d0505a2', 0, 'failedTransferCleanup', '"reject" "%SIPUUID%" "%SIPDirectory%"');
INSERT INTO TasksConfigs (pk, taskType, taskTypePKReference, description) VALUES ('1fea5138-981f-4fef-9d74-4d6328fb9248', '36b2e239-4a57-4aa5-8ebc-7a29139baca6', '72f11e68-7350-42a7-9bdc-60001d0505a2', 'Cleanup rejected transfer');
INSERT INTO MicroServiceChainLinks(pk, microserviceGroup, defaultExitMessage, currentTask, defaultNextChainLink) values ('ae5cdd0d-2f81-4935-a380-d5c6f1337d93', 'Reject transfer', 'Failed', '1fea5138-981f-4fef-9d74-4d6328fb9248', '333532b9-b7c2-4478-9415-28a3056d58df');
INSERT INTO MicroServiceChainLinksExitCodes (pk, microServiceChainLink, exitCode, nextMicroServiceChainLink, exitMessage) VALUES ('e8b5ea83-a108-48b4-af8e-42fa6794b1de', 'ae5cdd0d-2f81-4935-a380-d5c6f1337d93', 0, '333532b9-b7c2-4478-9415-28a3056d58df', 'Completed successfully');
UPDATE MicroServiceChains SET startingLink='ae5cdd0d-2f81-4935-a380-d5c6f1337d93' WHERE pk='1b04ec43-055c-43b7-9543-bd03c6a778ba';
