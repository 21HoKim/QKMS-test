run:
	$(MAKE) -C src/qkms/
	@echo "===================="
	@./build/main

clean: ./build/main
	rm -f ./build/*