package com.horsecoder.common.whuTalent.skilllab;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.netflix.eureka.server.EnableEurekaServer;
import org.springframework.cloud.openfeign.EnableFeignClients;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

@SpringBootApplication
public class SkillLabApplication {
    public static void main(String[] args) {
        SpringApplication.run(SkillLabApplication.class, args);
    }
}

@Configuration
@Profile("eureka")
@EnableEurekaServer
class EurekaConfiguration {}

@Configuration
@Profile("flow")
@EnableFeignClients(clients = {RegistryClient.class, WorkerClient.class})
class FlowConfiguration {}
